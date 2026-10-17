"""Privacy and spending: what reaches a remote provider (checked on the wire), monthly limits and the call log."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.core.types import ChatRequest, Message
from spike.providers.guard import GuardedProvider, call_cost, redact, usage_tokens
from spike.providers.openai_compat import OpenAICompatProvider
from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.db import Store
from tests.helpers import ScriptedProvider, call, text

SECRET = "ZX-ALBATROS-9931"
FILE = f"Proyecto Albatros\nEl código de acceso del proyecto Albatros es {SECRET}.\n"


def sse(*objs) -> bytes:
    return "".join(f"data: {o if isinstance(o, str) else json.dumps(o)}\n\n" for o in objs).encode()


class Remote:
    """A fake OpenAI-compatible API: asks for the file once, then answers; keeps every request body it receives."""

    def __init__(self, usage: bool = True):
        self.bodies: list[str] = []
        self.usage = usage

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        first = len(self.bodies) == 1
        delta = ({"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {
            "name": "read_file", "arguments": json.dumps({"path": "notas.txt"})}}]} if first
            else {"content": "No puedo ver el archivo."})
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if first else "stop"}]}]
        if self.usage:
            chunks.append({"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
        return httpx.Response(200, content=sse(*chunks, "[DONE]"), headers={"content-type": "text/event-stream"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    remote = Remote()
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        if cfg.kind == "openai":
            return OpenAICompatProvider(cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(remote)))
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    r = client.post("/api/providers", json={"preset": "openai", "api_key": "sk-test", "model": "gpt-test",
                                            "allow_paid": True})
    assert r.status_code == 200, r.text
    return client, state, remote, scripts


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def project_with_file(client) -> str:
    pid = client.post("/api/projects", json={"name": "Albatros"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/files/notas.txt", content=FILE.encode())
    assert r.status_code == 200 and r.json()["indexed"], r.text
    return pid


def ask(client, pid, provider="openai"):
    client.put("/api/settings", json={"tool_policies": {"read_file": "allow"}})
    return events_of(client.post("/api/chat", json={
        "message": "Lee notas.txt y dime el código de acceso del proyecto Albatros", "mode": "core",
        "provider_id": provider, "project_id": pid}))


def test_remote_provider_never_receives_file_contents(env):
    client, _, remote, _ = env
    pid = project_with_file(client)
    evs = ask(client, pid)
    assert [e for e in evs if e["type"] == "error"] == []
    assert len(remote.bodies) == 2  # the model asked for the file and got the notice instead
    assert all(SECRET not in body for body in remote.bodies)
    assert all("Albatros es" not in body for body in remote.bodies)  # memory's file passage did not go either
    assert "file content withheld" in remote.bodies[0]  # the recalled file passage, in the system prompt
    tool_msg = [m for m in json.loads(remote.bodies[1])["messages"] if m["role"] == "tool"]
    assert len(tool_msg) == 1 and tool_msg[0]["content"].startswith("[file content withheld: OpenAI")
    privacy = [e for e in evs if e["type"] == "privacy"]
    assert privacy and all(e["provider"] == "OpenAI" for e in privacy)
    tool_result = next(e for e in evs if e["type"] == "tool_result")
    assert SECRET in tool_result["content"]  # the user still sees what the tool read, in their own app

    log = client.get("/api/calls?remote=true").json()
    assert [c["status"] for c in log] == ["ok", "ok"] and {c["provider_id"] for c in log} == {"openai"}
    assert sum(c["files_withheld"] for c in log) >= 2 and all(c["files_sent"] == 0 for c in log)
    assert log[0]["tokens_in"] == 1000 and log[0]["tokens_out"] == 200 and not log[0]["estimated"]


def test_allowing_files_sends_them(env):
    """The control for the test above: the same check does see the secret once the user allows files."""
    client, _, remote, _ = env
    assert client.patch("/api/providers/openai", json={"share_files": True}).json()["share_files"] is True
    pid = project_with_file(client)
    evs = ask(client, pid)
    assert [e for e in evs if e["type"] == "privacy"] == []
    assert SECRET in remote.bodies[0] and SECRET in remote.bodies[1]
    assert client.get("/api/calls?remote=true").json()[0]["files_sent"] >= 1


def test_local_provider_receives_files(env):
    client, _, remote, scripts = env
    pid = project_with_file(client)
    client.get("/api/providers")
    scripts["spike-local"]._script = [call("read_file", {"path": "notas.txt"}), text("Es ", SECRET)]
    evs = ask(client, pid, provider="spike-local")
    assert remote.bodies == []
    tool_msg = [m for m in scripts["spike-local"].requests[1].messages if m.role == "tool"]
    assert SECRET in tool_msg[0].content
    assert [e for e in evs if e["type"] == "privacy"] == []


def test_monthly_token_limit_blocks_before_any_request(env):
    client, state, remote, _ = env
    r = client.patch("/api/providers/openai", json={"limits": {"monthly_tokens": 1000}})
    assert r.json()["limits"]["monthly_tokens"] == 1000
    state.store.log_call(provider_id="openai", provider="OpenAI", status="ok", tokens_in=900, tokens_out=150)
    evs = events_of(client.post("/api/chat", json={"message": "hola", "mode": "core", "provider_id": "openai"}))
    errors = [e["message"] for e in evs if e["type"] == "error"]
    assert errors and "monthly limit is reached (1,050 of 1,000 tokens" in errors[0]
    assert remote.bodies == []
    assert client.get("/api/calls?limit=1").json()[0]["status"] == "blocked"
    usage = {u["provider_id"]: u for u in client.get("/api/usage").json()}
    assert usage["openai"]["tokens_in"] == 900 and usage["openai"]["limits"]["monthly_tokens"] == 1000


def test_spending_limit_uses_the_prices_the_user_entered(env):
    client, state, remote, _ = env
    client.patch("/api/providers/openai", json={"limits": {"price_in": 2.0, "price_out": 10.0, "monthly_cost": 1.0}})
    events_of(client.post("/api/chat", json={"message": "hola", "mode": "core", "provider_id": "openai"}))
    first = client.get("/api/calls?limit=1").json()[0]
    assert first["cost"] == pytest.approx(1000 * 2 / 1e6 + 200 * 10 / 1e6)
    state.store.log_call(provider_id="openai", provider="OpenAI", status="ok", cost=1.5)
    evs = events_of(client.post("/api/chat", json={"message": "hola", "mode": "core", "provider_id": "openai"}))
    assert any("monthly spending limit is reached" in e.get("message", "") for e in evs)


def test_limits_are_validated(env):
    client, *_ = env
    assert client.patch("/api/providers/openai", json={"limits": {"monthly_tokens": -5}}).status_code == 422
    assert client.patch("/api/providers/openai", json={"limits": {"price_in": -1}}).status_code == 422


def test_paid_call_without_authorization_is_logged_as_blocked(env):
    client, _, remote, _ = env
    client.patch("/api/providers/openai", json={"allow_paid": False})
    evs = events_of(client.post("/api/chat", json={"message": "hola", "mode": "core", "provider_id": "openai"}))
    assert any("may bill your account" in e.get("message", "") for e in evs)
    assert remote.bodies == [] and client.get("/api/calls?limit=1").json()[0]["status"] == "blocked"


# ---------------------------------------------------------------- units
def test_redact_withholds_the_whole_message_when_a_part_is_missing():
    msgs = [Message(role="tool", content="abc SECRET def", private=["SECRET"]),
            Message(role="tool", content="changed", private=["not there"]),
            Message(role="user", content="SECRET in the user's own words stays")]
    out, n = redact(msgs, "[x]")
    assert [m.content for m in out] == ["abc [x] def", "[x]", "SECRET in the user's own words stays"]
    assert n == 2 and all(not m.private for m in out)


def test_usage_and_cost_helpers():
    assert usage_tokens({"prompt_tokens": 10, "completion_tokens": 2}) == (10, 2)
    assert usage_tokens({"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 5}) == (15, 2)
    assert usage_tokens({"timings": {}}) is None
    assert call_cost({}, 10, 10) is None
    assert call_cost({"price_in": 1.0}, 1_000_000, 5) == pytest.approx(1.0)


async def test_guard_estimates_tokens_when_the_provider_reports_none(tmp_path):
    store = Store(tmp_path / "s.db")
    inner = ScriptedProvider([text("una respuesta corta")], name="x")
    inner.config.local = False
    guard = GuardedProvider(inner, store)
    out = [e async for e in guard.stream(ChatRequest(messages=[Message(role="user", content="hola " * 30)]))]
    assert [e.kind for e in out] == ["text", "done"]
    row = store.calls()[0]
    assert row["estimated"] and row["tokens_in"] > 0 and row["tokens_out"] > 0 and row["status"] == "ok"


async def test_guard_logs_a_call_cut_short(tmp_path):
    store = Store(tmp_path / "s.db")
    guard = GuardedProvider(ScriptedProvider([text("a", "b", "c")], name="x"), store)
    gen = guard.stream(ChatRequest(messages=[Message(role="user", content="hola")]))
    await gen.__anext__()
    await gen.aclose()  # the user pressed stop
    assert store.calls()[0]["status"] == "cancelled"


def test_an_answer_written_from_a_file_is_not_sent_to_a_remote_later(env):
    """Turn 1: the local model reads the file and quotes it. Turn 2, same chat, on OpenAI: that answer is withheld."""
    client, state, remote, scripts = env
    pid = project_with_file(client)
    client.get("/api/providers")
    scripts["spike-local"]._script = [call("read_file", {"path": "notas.txt"}), text("El código es ", SECRET)]
    first = ask(client, pid, provider="spike-local")
    cid = next(e["id"] for e in first if e["type"] == "conversation")
    stored = [m for m in state.store.messages(cid) if m["role"] == "assistant"]
    assert stored[0]["meta"]["private"] is True
    remote.bodies.clear()
    remote.usage = False
    second = events_of(client.post("/api/chat", json={"message": "¿Y en inglés?", "conversation_id": cid,
                                                      "mode": "core", "provider_id": "openai"}))
    assert all(SECRET not in body for body in remote.bodies)
    sent = json.loads(remote.bodies[0])["messages"]
    assert [m["content"] for m in sent if m["role"] == "assistant"][0].startswith("[file content withheld")
    assert any(e["type"] == "privacy" for e in second)
    # the remote's own answers, which never saw the file, stay usable for the next remote turn
    last = [m for m in state.store.messages(cid) if m["role"] == "assistant"][-1]
    assert not last["meta"].get("private") and last["meta"]["privacy"] == {"OpenAI": 2}
    assert client.get("/api/calls?remote=true&limit=1").json()[0]["estimated"] is True


async def test_a_specialist_report_written_from_a_file_is_withheld_from_a_remote_synthesis(tmp_path):
    from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
    from spike.specialists.catalog import load_catalog
    from spike.tools.base import PermissionBroker
    from spike.tools.builtin import default_registry

    (tmp_path / "notas.txt").write_text(FILE, encoding="utf-8")
    plan = {"subtasks": [
        {"id": "t1", "specialist": "finance", "instruction": "Lee notas.txt", "depends_on": []},
        {"id": "t2", "specialist": "marketing", "instruction": "Un eslogan", "depends_on": ["t1"]},
    ]}
    store = Store(tmp_path / "s.db")
    local = ScriptedProvider([call("read_file", {"path": "notas.txt"}), text("Dice ", SECRET)], name="local")
    local.config.local = True
    remote = ScriptedProvider([text(json.dumps(plan)), text("ESLOGAN"), text('{"results": []}'), text("FINAL")],
                              name="remote")
    guarded_local, guarded_remote = GuardedProvider(local, store), GuardedProvider(remote, store)

    def resolve(spec):
        return Backend(provider=guarded_local if spec.id == "finance" else guarded_remote, model=None, adapter=None)

    orch = Orchestrator(load_catalog(), resolve, default_registry(tmp_path), PermissionBroker())
    orch.broker.policies["read_file"] = "allow"
    events = [e async for e in orch.run([], "Plan a marketing campaign for our ETF and estimate the ROI of the investment",
                                        OrchestratorOptions())]
    assert next(e for e in events if e["type"] == "plan")["method"] == "llm"
    assert SECRET in local.requests[1].messages[-1].content  # the local specialist did read it
    sent = [m.content for r in remote.requests for m in r.messages]
    assert all(SECRET not in c for c in sent)
    assert "[file content withheld" in remote.requests[1].messages[-1].content  # dependency input to marketing
    assert "[file content withheld" in remote.requests[2].messages[-1].content  # the checker
    assert "[file content withheld" in remote.requests[3].messages[-1].content  # the synthesis
    assert events[-1]["text"] == "FINAL" and events[-1]["private"] is False
