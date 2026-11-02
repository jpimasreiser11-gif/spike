"""The browser recorder and replay through the app (A16): the routes the Settings panel uses, the state wiring that
makes the connector's tools tell the recorder what they ran, and the rule that only this computer may use them. The
replay runs against a fake browser (tests/helpers_view.py); the real Playwright server is in tests/test_recorder.py."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from spike.connectors.manager import Connection, ConnectorDef
from spike.connectors.mcp import CallResult
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers_view import FakeBackend

LOCAL = ("127.0.0.1", 50_000)  # a request from this computer; the test client's own name is not one
ROLE = {"by": "role", "role": "button", "name": "Enviar pedido", "exact": False}


class Page:
    """Stands in for the Playwright MCP client: results as the real server words them."""

    def __init__(self):
        self.calls = []

    async def close(self):
        pass

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        code = {"browser_navigate": f"await page.goto('{args.get('url')}');",
                "browser_click": "await page.getByRole('button', { name: 'Enviar pedido' }).click();",
                "browser_type": "await page.getByRole('textbox', { name: 'Clave' }).fill('x');"}[name]
        return CallResult(text=f"### Ran Playwright code\n```js\n{code}\n```\n### Page\n- Page URL: https://shop.test/\n",
                          is_error=False, raw={})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path)
    with TestClient(create_app(state), client=LOCAL) as client:
        yield client, state


def run_view(state, backend=None):
    """Make View look started: a running connection whose tools are the manager's own (so they tell the recorder)."""
    page = Page()
    definition = state.connectors.get("playwright")
    assert isinstance(definition, ConnectorDef)
    conn = Connection(client=page, status="running")
    for remote in ("browser_navigate", "browser_click", "browser_type"):
        tool = state.connectors.make_tool(definition, page, {"name": remote}, f"mcp__playwright__{remote}", "allow")
        conn.by_remote[remote], conn.tools = tool, [*conn.tools, tool]
    state.connectors.connections["playwright"] = conn
    if backend is not None:
        state.replayer.backend = backend
    return conn, page


def wait_for(client, predicate, what, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = client.get("/api/browser/recorder").json()
        if predicate(status):
            return status
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}: {status}")


def test_the_panel_asks_what_is_going_on(env):
    client, _ = env
    status = client.get("/api/browser/recorder").json()
    assert status["running"] is False and status["recording"]["recording"] is False
    assert status["replay"]["state"] == "idle" and status["scripts"] == []


def test_recording_needs_view_to_run_and_one_recording_at_a_time(env):
    client, state = env
    assert client.post("/api/browser/recorder/start", json={"name": "x"}).status_code == 409  # View is off
    run_view(state)
    assert client.post("/api/browser/recorder/start", json={"name": "x"}).status_code == 200
    assert client.post("/api/browser/recorder/start", json={"name": "y"}).status_code == 409
    assert client.post("/api/browser/recorder/cancel").json()["recording"]["recording"] is False
    assert client.post("/api/browser/recorder/stop").status_code == 409  # nothing is being recorded
    assert client.post("/api/browser/recorder/start", json={"name": "x" * 500}).status_code == 422


async def test_what_the_connector_tools_run_is_recorded_and_kept(env):
    client, state = env
    conn, page = run_view(state)
    assert client.post("/api/browser/recorder/start", json={"name": "Mi pedido"}).json()["recording"] is True
    await conn.by_remote["browser_navigate"].run({"url": "https://shop.test/"})
    await conn.by_remote["browser_type"].run({"element": "Clave textbox", "target": "e4", "text": "hunter2-privada"})
    await conn.by_remote["browser_click"].run({"element": "Enviar pedido", "target": "e12"})
    live = client.get("/api/browser/recorder").json()["recording"]
    assert [s["action"] for s in live["steps"]] == ["navigate", "type", "click"]
    assert live["steps"][1]["secret"] is True and "text" not in live["steps"][1]
    assert live["steps"][2]["submits"] is True
    done = client.post("/api/browser/recorder/stop").json()
    assert done["saved"] == {"id": "mi-pedido", "name": "Mi pedido", "steps": 3, "truncated": False, "ignored": {}}
    assert [s["id"] for s in client.get("/api/browser/recorder").json()["scripts"]] == ["mi-pedido"]
    script = client.get("/api/browser/scripts/mi-pedido").json()
    assert script["steps"][1]["secret"] is True and "hunter2-privada" not in str(script)
    assert (state.home / "view-scripts" / "mi-pedido.json").is_file() and "hunter2-privada" not in (
        state.home / "view-scripts" / "mi-pedido.json").read_text(encoding="utf-8")
    assert len(page.calls) == 3


def test_a_recording_with_nothing_in_it_keeps_nothing(env):
    client, state = env
    run_view(state)
    client.post("/api/browser/recorder/start", json={"name": "vacío"})
    assert client.post("/api/browser/recorder/stop").json()["saved"] is None
    assert client.get("/api/browser/recorder").json()["scripts"] == []


def test_scripts_can_be_read_marked_secret_and_deleted(env):
    client, state = env
    sid = state.scripts.save({"name": "x", "steps": [
        {"action": "type", "target": ROLE, "text": "1234", "element": "Código"}]})
    assert client.post(f"/api/browser/scripts/{sid}/secret/0").json() == {"ok": True}
    assert "text" not in client.get(f"/api/browser/scripts/{sid}").json()["steps"][0]
    assert client.post(f"/api/browser/scripts/{sid}/secret/5").status_code == 400
    assert client.get("/api/browser/scripts/nada").status_code == 404
    for bad in ("Bad.Id", "..etc", "x" * 80):  # not an id this store makes (a path with a slash never reaches the route)
        assert client.get(f"/api/browser/scripts/{bad}").status_code == 404, bad
        assert client.delete(f"/api/browser/scripts/{bad}").status_code == 404, bad
    assert client.delete(f"/api/browser/scripts/{sid}").json() == {"ok": True}
    assert client.delete(f"/api/browser/scripts/{sid}").status_code == 404


def test_a_replay_asks_before_a_submit_and_waits_for_the_answer(env):
    client, state = env
    backend = FakeBackend(domains={"shop.test": "allow"})
    run_view(state, backend)
    sid = state.scripts.save({"name": "pedido", "steps": [
        {"action": "navigate", "url": "https://shop.test/"},
        {"action": "click", "target": ROLE, "element": "Enviar pedido", "submits": True},
        {"action": "navigate", "url": "https://shop.test/gracias"}]})
    started = client.post("/api/browser/replay", json={"script": sid}).json()
    assert started["state"] in ("running", "waiting") and started["total"] == 3
    waiting = wait_for(client, lambda s: s["replay"]["question"], "the question")["replay"]
    question = waiting["question"]
    assert (question["kind"], question["code"], question["step"]) == ("submit", "click_submit", 1)
    assert len(backend.calls) == 1  # only the first navigation ran
    assert client.post("/api/browser/replay", json={"script": sid}).status_code == 409  # one at a time
    assert client.delete(f"/api/browser/scripts/{sid}").status_code == 409  # not while it is being replayed
    assert client.post("/api/browser/replay/answer", json={"question": "otra", "decision": "allow_once"}).status_code == 409
    assert client.post("/api/browser/replay/answer",
                       json={"question": question["id"], "decision": "allow_always"}).status_code == 409
    assert client.post("/api/browser/replay/answer",
                       json={"question": question["id"], "decision": "allow_once"}).json() == {"ok": True}
    done = wait_for(client, lambda s: s["replay"]["state"] == "done", "the end")["replay"]
    assert [s["status"] for s in done["steps"]] == ["done", "done", "done"] and len(backend.calls) == 3


def test_stop_ends_a_replay_at_any_time(env):
    client, state = env
    backend = FakeBackend(domains={"shop.test": "allow"})
    run_view(state, backend)
    sid = state.scripts.save({"name": "pedido", "steps": [
        {"action": "navigate", "url": "https://shop.test/"}, {"action": "press", "key": "Enter"}]})
    client.post("/api/browser/replay", json={"script": sid, "mode": "auto"})
    wait_for(client, lambda s: s["replay"]["question"], "the question")
    assert client.post("/api/browser/replay/stop").json() == {"ok": True}
    status = client.get("/api/browser/recorder").json()["replay"]
    assert status["state"] == "stopped" and status["question"] is None and len(backend.calls) == 1
    assert client.post("/api/browser/replay/stop").json() == {"ok": False}


def test_a_replay_needs_view_and_a_script_that_exists(env):
    client, state = env
    sid = state.scripts.save({"name": "x", "steps": [{"action": "navigate", "url": "https://shop.test/"}]})
    assert client.post("/api/browser/replay", json={"script": sid}).status_code == 409  # View is off
    run_view(state, FakeBackend())
    assert client.post("/api/browser/replay", json={"script": "nada"}).status_code == 404
    assert client.post("/api/browser/replay", json={"script": sid, "mode": "turbo"}).status_code == 422


def test_the_real_connector_backend_is_the_one_the_app_uses(env):
    client, state = env
    assert client.get("/api/browser/recorder").json()["running"] is False
    run_view(state)
    assert client.get("/api/browser/recorder").json()["running"] is True
    assert state.recorder.store is state.scripts and state.replayer.store is state.scripts
    assert state.recorder.observe in state.connectors.observers


def test_only_this_computer_can_record_or_replay(env):
    _, state = env
    sid = state.scripts.save({"name": "x", "steps": [{"action": "navigate", "url": "https://shop.test/"}]})
    with TestClient(create_app(state), client=("203.0.113.9", 4000)) as stranger:
        for method, path, body in [
                ("get", "/api/browser/recorder", None), ("post", "/api/browser/recorder/start", {"name": "x"}),
                ("post", "/api/browser/recorder/stop", None), ("post", "/api/browser/recorder/cancel", None),
                ("get", f"/api/browser/scripts/{sid}", None), ("delete", f"/api/browser/scripts/{sid}", None),
                ("post", f"/api/browser/scripts/{sid}/secret/0", None),
                ("post", "/api/browser/replay", {"script": sid}),
                ("post", "/api/browser/replay/answer", {"question": "q", "decision": "stop"}),
                ("post", "/api/browser/replay/stop", None)]:
            response = getattr(stranger, method)(path, **({"json": body} if body is not None else {}))
            assert response.status_code == 403, (path, response.status_code)
    assert state.scripts.list()[0]["id"] == sid  # nothing was deleted


def test_geo_and_architecture_tools_are_registered_for_chats_projects_and_specialists(env):
    _, state = env
    names = ("geo_map", "geo_measure", "architecture_graph")
    for registry in (state.tools, state.tools_for("p1")):
        assert all(registry.get(n) is not None and registry.get(n).risk == "read" for n in names)
    assert set(names) <= set(state.catalog.get("core").tools)
    assert "architecture_graph" in state.catalog.get("code").tools
    assert {"geo_map", "geo_measure"} <= set(state.catalog.get("data").tools)
