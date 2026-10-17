import json

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    return TestClient(create_app(state)), state, scripts


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_health_system_specialists(env):
    client, _, _ = env
    assert client.get("/api/health").json()["ok"]
    sysinfo = client.get("/api/system").json()
    assert sysinfo["hardware"]["total_ram_gb"] > 0 and sysinfo["secrets_backend"] == "file-0600"
    specs = client.get("/api/specialists").json()
    assert {s["id"] for s in specs} >= {"core", "finance", "medicine"}


def test_provider_crud_keeps_keys_out_of_db(env, tmp_path):
    client, state, _ = env
    r = client.post("/api/providers", json={"preset": "deepseek", "api_key": "sk-secret", "model": "deepseek-chat"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_key"] and body["paid"] and not body["allow_paid"] and "api_key" not in body
    assert b"sk-secret" not in (tmp_path / "spike.db").read_bytes()
    assert state.secrets.get("provider:deepseek") == "sk-secret"
    assert client.patch("/api/providers/deepseek", json={"allow_paid": True}).json()["allow_paid"] is True
    assert client.post("/api/providers", json={"preset": "deepseek"}).status_code == 409
    assert client.delete("/api/providers/deepseek").json()["ok"]
    assert state.secrets.get("provider:deepseek") is None
    assert client.delete("/api/providers/spike-local").status_code == 400


def test_chat_streams_and_persists(env):
    client, _, scripts = env
    client.get("/api/providers")  # instantiate providers
    scripts["spike-local"]._script = [text("Hola ", "joan")]
    r = client.post("/api/chat", json={"message": "Hola, ¿qué tal?"})
    evs = events_of(r)
    assert evs[0]["type"] == "conversation"
    assert [e["type"] for e in evs][-1] == "done" and evs[-1]["text"] == "Hola joan"
    conv = client.get(f"/api/conversations/{evs[0]['id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["meta"]["route"]["mode"] == "direct"
    # follow-up includes history
    scripts["spike-local"]._script = [text("ok")]
    client.post("/api/chat", json={"message": "y ahora?", "conversation_id": evs[0]["id"]})
    req = scripts["spike-local"].requests[-1]
    assert [m.content for m in req.messages if m.role != "system"] == ["Hola, ¿qué tal?", "Hola joan", "y ahora?"]


def test_custom_instructions_reach_the_model(env):
    client, _, scripts = env
    client.get("/api/providers")
    client.put("/api/settings", json={"custom_instructions": "Siempre responde en español."})
    scripts["spike-local"]._script = [text("vale")]
    client.post("/api/chat", json={"message": "Explain EBITDA", "mode": "finance"})
    system = scripts["spike-local"].requests[-1].messages[0].content
    assert "Spike Finance" in system and "Siempre responde en español." in system
    assert client.put("/api/settings", json={"nope": 1}).status_code == 400


def test_chat_with_permissioned_tool_and_decision_endpoint(env, tmp_path):
    client, state, scripts = env
    client.get("/api/providers")
    # write_file asks for permission; deny it via policy to keep the test synchronous
    client.put("/api/settings", json={"tool_policies": {"write_file": "deny"}})
    scripts["spike-local"]._script = [call("write_file", {"path": "a.txt", "content": "x"}), text("could not write")]
    evs = events_of(client.post("/api/chat", json={"message": "write a file", "mode": "core"}))
    result = next(e for e in evs if e["type"] == "tool_result")
    assert result["ok"] is False and "disabled" in result["content"]
    assert not (tmp_path / "ws" / "a.txt").exists()
    assert client.post("/api/permissions/nope", json={"decision": "allow_once"}).status_code == 404


def test_unknown_mode_and_provider_rejected(env):
    client, _, _ = env
    assert client.post("/api/chat", json={"message": "x", "mode": "astrology"}).status_code == 400
    assert client.post("/api/chat", json={"message": "x", "provider_id": "nope"}).status_code == 400


def test_runtime_start_without_model_is_explained(env):
    client, _, _ = env
    r = client.post("/api/runtime/start")
    assert r.status_code == 400 and "No local model configured" in r.json()["detail"]
