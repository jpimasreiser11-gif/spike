"""Temporary chats: kept in memory only, without SPIKE's memory, and gone when the app stops."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, state, local, tmp_path


def chat(client, local, body, reply="Vale."):
    local._script = [text(reply)]
    return [json.loads(line[6:]) for line in client.post("/api/chat", json={"mode": "core", **body}).text.splitlines()
            if line.startswith("data: ")]


def test_a_temporary_chat_is_never_written_and_uses_no_memory(env):
    client, state, local, home = env
    client.post("/api/memory", json={"text": "Responde siempre en catalán", "kind": "rule"})
    secret = "Mi diagnóstico es confidencial: código ZX-4471"
    events = chat(client, local, {"message": secret, "temporary": True}, reply="Entendido.")
    conv = next(e for e in events if e["type"] == "conversation")
    assert conv["temporary"] is True
    assert "catalán" not in local.requests[-1].messages[0].content  # rules and notes are not read
    assert not any(e["type"] == "memory" for e in events)

    chat(client, local, {"message": "Recuerda que trabajo en Girona", "conversation_id": conv["id"]})
    assert [m.role for m in local.requests[-1].messages[1:]] == ["user", "assistant", "user"]  # history kept
    assert [m.text for m in state.memory.store.list()] == ["Responde siempre en catalán"]  # nothing learned

    assert client.get("/api/conversations").json() == []
    stored = client.get(f"/api/conversations/{conv['id']}").json()
    assert stored["temporary"] is True and len(stored["messages"]) == 4
    state.store._conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert not any(b"ZX-4471" in f.read_bytes() for f in home.glob("spike.db*"))

    restarted = TestClient(create_app(AppState(home=home)))
    assert restarted.get(f"/api/conversations/{conv['id']}").status_code == 404


def test_a_temporary_chat_can_be_deleted_and_normal_chats_are_unchanged(env):
    client, state, local, _ = env
    temp = next(e for e in chat(client, local, {"message": "hola", "temporary": True}) if e["type"] == "conversation")
    normal = next(e for e in chat(client, local, {"message": "hola"}) if e["type"] == "conversation")
    assert "temporary" not in normal and [c["id"] for c in client.get("/api/conversations").json()] == [normal["id"]]
    assert client.patch(f"/api/conversations/{temp['id']}", json={"title": "Prueba"}).json()["title"] == "Prueba"
    client.delete(f"/api/conversations/{temp['id']}")
    assert client.get(f"/api/conversations/{temp['id']}").status_code == 404
    assert state.store.get_conversation(normal["id"])
