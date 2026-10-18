"""Connectors: an MCP server's tools become SPIKE tools behind the same permission broker (allow / ask / deny)."""

import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml

from spike.connectors.manager import CATALOG, load_catalog, tool_name
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text

pytest.importorskip("mcp.server.mcpserver", reason="the official MCP SDK (dev dependency) builds the test server")
SERVER = str(Path(__file__).parent / "fixtures" / "mcp_test_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60)
    yield client, state, local
    server.should_exit = True
    thread.join(timeout=10)


def add_test_connector(client, **extra) -> dict:
    r = client.post("/api/connectors", json={"id": "test", "name": "Test", "transport": "stdio",
                                             "command": sys.executable, "args": [SERVER], **extra})
    assert r.status_code == 200, r.text
    r = client.put("/api/connectors/test", json={"enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def chat_events(client, message: str, on_event=None) -> list[dict]:
    events = []
    with client.stream("POST", "/api/chat", json={"message": message, "mode": "core"}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                events.append(ev)
                if on_event:
                    on_event(ev)
    return events


def test_enabling_a_connector_exposes_its_tools_with_ask_by_default(app):
    client, _, _ = app
    view = add_test_connector(client)
    assert view["status"] == "running", view["error"]
    assert {t["name"] for t in view["tools"]} == {"mcp__test__add", "mcp__test__shout", "mcp__test__env",
                                                  "mcp__test__fail"}
    assert {t["policy"] for t in view["tools"]} == {"ask"}
    listed = {t["name"]: t for t in client.get("/api/tools").json()}
    assert listed["mcp__test__add"]["policy"] == "ask" and listed["mcp__test__add"]["risk"] == "network"
    assert client.put("/api/connectors/test", json={"enabled": False}).json()["status"] == "stopped"
    assert "mcp__test__add" not in {t["name"] for t in client.get("/api/tools").json()}


def test_allowed_call_reaches_the_server_and_the_model_sees_the_result(app):
    client, _, local = app
    add_test_connector(client, )
    client.put("/api/connectors/test", json={"policy": "allow"})
    local._script = [call("mcp__test__add", {"a": 2, "b": 3}), text("2 + 3 = 5")]
    events = chat_events(client, "add 2 and 3")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] and result["content"] == "5"
    assert "mcp__test__add" in [t.name for t in local.requests[0].tools]  # offered to the specialist
    assert local.requests[-1].messages[-1].content == "5"


def test_per_tool_deny_overrides_the_connector(app):
    client, _, local = app
    add_test_connector(client)
    client.put("/api/connectors/test", json={"policy": "allow"})
    client.put("/api/settings", json={"tool_policies": {"mcp__test__add": "deny"}})
    local._script = [call("mcp__test__add", {"a": 1, "b": 1}), text("blocked")]
    result = next(e for e in chat_events(client, "add") if e["type"] == "tool_result")
    assert not result["ok"] and "disabled" in result["content"]


def test_ask_waits_for_the_user_and_runs_after_approval(app):
    client, _, local = app
    add_test_connector(client)
    local._script = [call("mcp__test__shout", {"text": "hola"}), text("done")]
    approver = httpx.Client(base_url=client.base_url, timeout=10)

    def approve(ev):
        if ev["type"] == "permission_request":
            assert ev["tool"] == "mcp__test__shout" and ev["arguments"] == {"text": "hola"}
            assert approver.post(f"/api/permissions/{ev['id']}", json={"decision": "allow_once"}).status_code == 200

    events = chat_events(client, "shout hola", approve)
    assert [e["decision"] for e in events if e["type"] == "permission_resolved"] == ["allow_once"]
    assert next(e for e in events if e["type"] == "tool_result")["content"] == "HOLA"


def test_secrets_go_to_the_server_as_env_and_never_back_to_the_client(app, monkeypatch):
    client, state, local = app
    monkeypatch.setenv("SPIKE_API_TOKEN", "never-for-mcp")
    view = add_test_connector(client, args=[SERVER])
    assert view["status"] == "running"
    custom = state.store.get_setting("custom_connectors")
    custom[0]["secrets"] = [{"name": "TEST_TOKEN", "label": "Test token"}]
    state.store.set_setting("custom_connectors", custom)
    view = client.put("/api/connectors/test", json={"enabled": True}).json()
    assert view["status"] == "error" and "Test token" in view["error"]
    view = client.put("/api/connectors/test", json={"secrets": {"TEST_TOKEN": "abc123"}, "policy": "allow"}).json()
    assert view["status"] == "running" and view["secrets_set"] == {"TEST_TOKEN": True}
    assert "abc123" not in json.dumps(client.get("/api/connectors").json())
    local._script = [call("mcp__test__env", {"name": "TEST_TOKEN"}), call("mcp__test__env", {"name": "SPIKE_API_TOKEN"}),
                     text("ok")]
    results = [e["content"] for e in chat_events(client, "env") if e["type"] == "tool_result"]
    assert results == ["abc123", ""]


def test_a_broken_server_is_reported_not_raised(app):
    client, _, local = app
    r = client.post("/api/connectors", json={"id": "broken", "name": "Broken", "command": "spike-no-such-cmd"})
    assert r.status_code == 200
    view = client.put("/api/connectors/broken", json={"enabled": True}).json()
    assert view["status"] == "error" and "cannot start" in view["error"]
    local._script = [text("still answers")]
    assert any(e.get("text") == "still answers" for e in chat_events(client, "hola"))
    assert client.delete("/api/connectors/broken").json()["ok"]


def test_custom_connector_validation_and_catalog_entries_cannot_be_deleted(app):
    client, state, _ = app
    assert client.post("/api/connectors", json={"id": "Bad Id", "name": "x", "command": "x"}).status_code == 400
    assert client.post("/api/connectors", json={"id": "h", "name": "x", "transport": "http", "url": "ftp://x"}).status_code == 400
    for entry in state.connectors.catalog[:1]:
        assert client.delete(f"/api/connectors/{entry.id}").status_code == 400


def test_tool_names_are_valid_function_names():
    assert tool_name("git-hub", "create issue/v2") == "mcp__git_hub__create_issue_v2"
    assert len(tool_name("a" * 30, "b" * 80)) == 64


def test_every_catalog_entry_is_complete_and_listed_in_third_party():
    entries = load_catalog()
    raw = yaml.safe_load(CATALOG.read_text())
    assert len(entries) == len(raw) >= 1
    third_party = (Path(__file__).parents[1] / "THIRD_PARTY.md").read_text()
    for e in entries:
        assert e.license and e.source.startswith("https://") and e.transport in ("stdio", "http"), e.id
        assert (e.command if e.transport == "stdio" else e.url), e.id
        assert e.source in third_party, f"{e.id} missing from THIRD_PARTY.md"
