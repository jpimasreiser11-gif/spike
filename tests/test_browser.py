"""Browser guard (C1): per-domain permissions and a confirmation before anything that submits a form, for the
Playwright connector. The last test drives the real Playwright MCP server and Chromium when they are installed
(SPIKE_PLAYWRIGHT_MCP = the playwright-mcp binary, SPIKE_CHROMIUM = a Chromium executable)."""

import asyncio
import http.server
import os
import re
import socket
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from spike.agent.loop import AgentRun, run_agent
from spike.connectors import browser
from spike.connectors.manager import ConnectorDef, ConnectorManager, McpTool
from spike.core.types import Message
from spike.store.db import Store
from spike.store.secrets import SecretStore
from spike.tools.base import HeadlessBroker, PermissionBroker
from tests.helpers import ScriptedProvider, call, text

SETTINGS = {"domains": {"example.com": "allow", "evil.test": "deny"}, "unknown": "ask"}


def test_pages_are_checked_by_domain():
    assert browser.review("browser_navigate", {"url": "https://shop.example.com/cart"}, SETTINGS).policy == "allow"
    blocked = browser.review("browser_navigate", {"url": "http://www.evil.test/x"}, SETTINGS)
    assert blocked.policy == "deny" and blocked.reason == "you blocked evil.test"
    new = browser.review("browser_navigate", {"url": "https://www.wikipedia.org/"}, SETTINGS)
    assert (new.policy, new.domain, new.once) == ("ask", "wikipedia.org", False)
    for url in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "not a url"):
        assert browser.review("browser_navigate", {"url": url}, SETTINGS).policy == "deny", url
    assert browser.review("browser_navigate", {"url": "about:blank"}, SETTINGS).policy == "allow"
    assert browser.review("browser_tabs", {"action": "new", "url": "https://evil.test"}, SETTINGS).policy == "deny"
    assert browser.review("browser_navigate", {"url": "https://wikipedia.org"},
                          {**SETTINGS, "unknown": "allow"}).policy == "allow"
    assert browser.blocked_origins(SETTINGS) == ["evil.test", "http://evil.test:*", "https://evil.test:*",
                                                 "*.evil.test", "http://*.evil.test:*", "https://*.evil.test:*"]


@pytest.mark.parametrize("remote,args", [
    ("browser_type", {"target": "e3", "text": "hola", "submit": True}),
    ("browser_type", {"target": "e3", "text": "hola\n"}),
    ("browser_press_key", {"key": "Enter"}),
    ("browser_click", {"element": "Enviar pedido", "target": "e9"}),
    ("browser_click", {"element": "Sign in", "target": "e2"}),
    ("browser_click", {"target": "button[type=submit]"}),
    ("browser_click", {"target": "e12"}),  # not described: it may be the submit button
    ("browser_file_upload", {"paths": ["/home/me/dni.pdf"]}),
    ("browser_evaluate", {"function": "() => document.cookie"}),
    ("browser_run_code_unsafe", {"code": "await page.goto('x')"}),
    ("browser_handle_dialog", {"accept": True}),
])
def test_submitting_and_sending_always_ask_once(remote, args):
    review = browser.review(remote, args, SETTINGS)
    assert review.policy == "ask" and review.once, remote


@pytest.mark.parametrize("remote,args", [
    ("browser_click", {"element": "Ver más detalles", "target": "e5"}),
    ("browser_type", {"target": "e3", "text": "hola"}),
    ("browser_press_key", {"key": "ArrowDown"}),
    ("browser_snapshot", {}),
    ("browser_handle_dialog", {"accept": False}),
])
def test_reading_and_typing_are_left_to_the_connector_policy(remote, args):
    assert browser.review(remote, args, SETTINGS) is None


# ---------------------------------------------------------------- through the broker and the agent loop
@dataclass
class Result:
    text: str
    is_error: bool = False


class FakeBrowser:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return Result(f"done: {name}")


@pytest.fixture
def manager(tmp_path):
    store = Store(tmp_path / "spike.db")
    return ConnectorManager(store, SecretStore(tmp_path / "secrets.json"), tmp_path / "ws", tmp_path / "connectors")


def tools(manager, fake, policy="ask"):
    definition = manager.get("playwright")
    return [McpTool(definition, fake, {"name": n, "inputSchema": {"type": "object"}}, f"mcp__playwright__{n}", policy,
                    manager._guard(definition)) for n in ("browser_navigate", "browser_type", "browser_snapshot")]


async def run(manager, script, broker, decide=None, policy="ask"):
    fake = FakeBrowser()
    events = []
    async for ev in run_agent(ScriptedProvider(script), [Message(role="user", content="go")],
                              tools=tools(manager, fake, policy), broker=broker, run=AgentRun()):
        events.append(ev)
        if ev["type"] == "permission_request" and decide:
            asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], decide(ev))
    return events, fake


async def test_a_new_domain_asks_and_can_be_allowed_for_good(manager):
    broker = PermissionBroker()
    broker.on_domain = manager.set_domain
    events, fake = await run(manager, [call("mcp__playwright__browser_navigate", {"url": "https://www.boe.es/x"}),
                                       text("ok")], broker, lambda ev: "allow_domain")
    request = next(e for e in events if e["type"] == "permission_request")
    assert request["domain"] == "boe.es" and request["reason"] == "opens boe.es" and request["once"] is False
    assert request["code"] == "open"
    assert fake.calls == [("browser_navigate", {"url": "https://www.boe.es/x"})]
    assert manager.browser_settings()["domains"] == {"boe.es": "allow"}
    events, fake = await run(manager, [call("mcp__playwright__browser_navigate", {"url": "https://boe.es/y"}),
                                       text("ok")], broker)  # no question this time, even with the connector on "ask"
    assert not any(e["type"] == "permission_request" for e in events) and len(fake.calls) == 1


async def test_a_blocked_domain_is_refused_without_asking(manager):
    manager.set_domain("www.evil.test", "deny")
    assert manager.browser_settings()["domains"] == {"evil.test": "deny"}
    events, fake = await run(manager, [call("mcp__playwright__browser_navigate", {"url": "https://a.evil.test"}),
                                       text("no")], PermissionBroker(), policy="allow")
    result = next(e for e in events if e["type"] == "tool_result")
    assert not result["ok"] and result["content"] == "error: refused: you blocked evil.test" and fake.calls == []
    with pytest.raises(ValueError):
        manager.set_domain("https://x y", "allow")


async def test_submitting_asks_every_time_even_after_allow_always(manager):
    broker = PermissionBroker()
    submit = call("mcp__playwright__browser_type", {"target": "e3", "text": "x", "submit": True})
    events, fake = await run(manager, [submit, text("sent")], broker, lambda ev: "allow_always", policy="allow")
    request = next(e for e in events if e["type"] == "permission_request")
    assert request["once"] is True and "submits" in request["reason"] and request["code"] == "type_submit"
    assert [e["decision"] for e in events if e["type"] == "permission_resolved"] == ["allow_once"]
    assert "mcp__playwright__browser_type" not in broker.session_allow and len(fake.calls) == 1
    events, _ = await run(manager, [submit, text("sent")], broker, lambda ev: "deny", policy="allow")
    assert next(e for e in events if e["type"] == "tool_result")["content"] == "error: the user denied this tool call"
    typing = call("mcp__playwright__browser_type", {"target": "e3", "text": "x"})
    events, _ = await run(manager, [typing, text("typed")], broker, policy="allow")
    assert not any(e["type"] == "permission_request" for e in events)


async def test_nobody_can_confirm_for_headless_callers(manager):
    submit = call("mcp__playwright__browser_type", {"target": "e3", "text": "x", "submit": True})
    events, fake = await run(manager, [submit, text("x")], HeadlessBroker(PermissionBroker()), policy="allow")
    assert "needs the user's approval" in next(e for e in events if e["type"] == "tool_result")["content"]
    assert fake.calls == []


def test_browser_settings_are_validated(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from spike.server.app import create_app
    from spike.server.state import AppState

    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    client = TestClient(create_app(AppState(home=tmp_path)))
    assert client.get("/api/browser").json() == {"domains": {}, "unknown": "ask"}
    assert client.put("/api/browser/domains/WWW.Example.com", json={"rule": "deny"}).json()["domains"] == {
        "example.com": "deny"}
    assert client.put("/api/browser/domains/a b", json={"rule": "allow"}).status_code == 400
    assert client.put("/api/browser", json={"unknown": "allow"}).json() == {"domains": {"example.com": "deny"},
                                                                           "unknown": "allow"}
    assert client.put("/api/browser", json={"unknown": "always"}).status_code == 422
    assert client.put("/api/browser/domains/example.com", json={"rule": None}).json()["domains"] == {}
    for bad in ({"unknown": "x"}, {"domains": {"a.com": "maybe"}}, {"domains": ["a.com"]}, {"other": 1}, "ask"):
        assert client.put("/api/settings", json={"browser": bad}).status_code == 400
    saved = client.put("/api/settings", json={"browser": {"domains": {"www.boe.es": "allow"}}}).json()["browser"]
    assert saved == {"domains": {"boe.es": "allow"}, "unknown": "ask"}


def test_blocked_domains_reach_the_browser_at_start(manager):
    manager.set_domain("evil.test", "deny")
    client = manager._client(manager.get("playwright"))
    assert client.transport.args[-2:] == ["--blocked-origins", ";".join(browser.blocked_origins(
        manager.browser_settings()))] and "evil.test" in client.transport.args[-1]


# ---------------------------------------------------------------- the real Playwright MCP server and Chromium
def run_text(events):
    return "".join(e["text"] for e in events if e["type"] == "delta")


PLAYWRIGHT = os.environ.get("SPIKE_PLAYWRIGHT_MCP")
CHROMIUM = os.environ.get("SPIKE_CHROMIUM")


class Site(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []
    form = """<!doctype html><html><head><title>Pedido</title></head><body>
<form method="post" action="/submit"><label>Nombre <input name="nombre"></label><button>Enviar pedido</button></form>
<img src="http://localhost:{port}/pixel" alt="pixel"></body></html>"""

    def do_GET(self):
        Site.hits.append(f"{self.headers['Host'].split(':')[0]} GET {self.path}")
        body = Site.form.format(port=self.server.server_port).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"])).decode()
        Site.hits.append(f"POST {data}")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<p>Gracias</p>")

    def log_message(self, *args):
        pass


@pytest.mark.skipif(not (PLAYWRIGHT and CHROMIUM and Path(PLAYWRIGHT).exists() and Path(CHROMIUM).exists()),
                    reason="needs SPIKE_PLAYWRIGHT_MCP and SPIKE_CHROMIUM")
async def test_real_browser_asks_before_submitting_and_blocks_domains(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Site.hits = []
    definition = ConnectorDef(id="playwright", name="Playwright browser", description="", transport="stdio",
                              command=PLAYWRIGHT, args=["--headless", "--isolated", "--no-sandbox",
                                                        "--executable-path", CHROMIUM])
    (tmp_path / "ws").mkdir()
    manager = ConnectorManager(Store(tmp_path / "spike.db"), SecretStore(tmp_path / "s.json"), tmp_path / "ws",
                               tmp_path / "c", catalog=[definition])
    manager.set_domain("localhost", "deny")  # before the start: the browser gets it as a blocked origin
    manager._save_config("playwright", policy="allow")
    conn = await manager.start("playwright")
    assert conn.status == "running", conn.error
    broker = PermissionBroker()
    broker.on_domain = manager.set_domain
    decisions = iter(["allow_domain", "deny", "allow_once"])

    def script(request):
        tool_msgs = [m for m in request.messages if m.role == "tool"]
        names = [m.name for m in tool_msgs]
        if not tool_msgs:
            return call("mcp__playwright__browser_navigate", {"url": f"http://127.0.0.1:{port}/form"}, "c1")
        if "mcp__playwright__browser_snapshot" not in names:  # actions save their snapshot to a file; ask for it
            return call("mcp__playwright__browser_snapshot", {}, "s1")
        ref = re.search(r'textbox "Nombre" \[ref=(\w+)\]', "\n".join(m.content for m in tool_msgs))
        tries = names.count("mcp__playwright__browser_type")
        if tries < 2:
            return call("mcp__playwright__browser_type", {"element": "Nombre", "target": ref.group(1), "text": "Ana",
                                                          "submit": True}, f"t{tries}")
        if names.count("mcp__playwright__browser_navigate") == 1:
            return call("mcp__playwright__browser_navigate", {"url": f"http://localhost:{port}/form"}, "c2")
        return text("hecho")

    events = []
    try:
        async for ev in run_agent(ScriptedProvider(script), [Message(role="user", content="haz el pedido")],
                                  tools=conn.tools, broker=broker, run=AgentRun(), max_steps=10):
            events.append(ev)
            if ev["type"] == "permission_request":
                asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], next(decisions))
    finally:
        await manager.close_all()
        server.shutdown()
    asks = [e for e in events if e["type"] == "permission_request"]
    assert [a.get("domain") for a in asks] == ["127.0.0.1", None, None] and asks[1]["once"] and asks[2]["once"]
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["ok"] and "Page Title: Pedido" in results[0]["content"]
    assert results[1]["ok"] and 'button "Enviar pedido"' in results[1]["content"]
    assert results[2]["content"] == "error: the user denied this tool call"
    assert results[3]["ok"]
    assert results[4]["content"] == "error: refused: you blocked localhost"
    assert run_text(events) == "hecho"
    assert Site.hits.count("POST nombre=Ana") == 1  # only the confirmed submission reached the site
    assert not any(h.startswith("localhost") for h in Site.hits)  # the page's image from the blocked domain
    assert manager.browser_settings()["domains"] == {"localhost": "deny", "127.0.0.1": "allow"}
