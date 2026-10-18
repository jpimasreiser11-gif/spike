"""MCP Apps (C6, SEP-1865): SPIKE announces the extension, keeps app-only tools from the model, serves only the
views a tool declared under a CSP of public https origins, and lets a view call only its own server's app tools
under the tool's policy, with an audit log."""

import json
import sys
from pathlib import Path

import pytest

from spike.connectors.apps import clean_csp, csp_policy, resource_from, result_for_view, tool_ui
from spike.connectors.mcp import APP_MIME, UI_EXTENSION, McpClient, StdioTransport
from tests.helpers import call, text
from tests.test_connectors import app, chat_events  # noqa: F401  (the live-server fixture)

pytest.importorskip("mcp.server.mcpserver", reason="the official MCP SDK (dev dependency) builds the test server")
SERVER = str(Path(__file__).parent / "fixtures" / "mcp_app_server.py")
VIEW = "ui://prices/view"


def test_tool_metadata_and_visibility():
    assert tool_ui({"_meta": {"ui": {"resourceUri": VIEW}}}) == (VIEW, ["model", "app"])
    assert tool_ui({"_meta": {"ui": {"resourceUri": VIEW, "visibility": ["app"]}}}) == (VIEW, ["app"])
    assert tool_ui({"_meta": {"ui/resourceUri": "ui://old"}}) == ("ui://old", ["model", "app"])  # deprecated key
    assert tool_ui({"_meta": {"ui": {"resourceUri": "https://evil.example/page"}}}) == (None, ["model", "app"])
    assert tool_ui({"name": "plain"}) == (None, ["model", "app"])


def test_only_public_https_origins_reach_the_policy():
    csp, dropped = clean_csp({"connectDomains": ["https://api.example.com", "wss://live.example.com/",
                                                 "http://api.example.com", "https://127.0.0.1", "https://localhost",
                                                 "https://192.168.1.10:8080", "https://printer.local"],
                              "resourceDomains": ["https://*.cdn.example.com", "javascript:alert(1)", "*"],
                              "frameDomains": "https://not-a-list.example.com"})
    assert csp == {"connectDomains": ["https://api.example.com", "wss://live.example.com"],
                   "resourceDomains": ["https://*.cdn.example.com"]}
    assert len(dropped) == 7
    policy = csp_policy(csp)
    assert "connect-src https://api.example.com wss://live.example.com" in policy
    assert "script-src 'unsafe-inline' https://*.cdn.example.com" in policy
    assert "frame-src 'none'" in policy and "object-src 'none'" in policy and "'self'" not in policy
    default = csp_policy({})
    assert "connect-src 'none'" in default and "script-src 'unsafe-inline';" in default


def test_a_view_must_be_an_app_page():
    page = {"contents": [{"uri": VIEW, "mimeType": APP_MIME, "text": "<p>hi</p>"}]}
    view = resource_from(VIEW, page)
    assert view["html"] == "<p>hi</p>" and view["policy"] == csp_policy({}) and len(view["sha256"]) == 64
    with pytest.raises(ValueError, match="not an MCP App page"):
        resource_from(VIEW, {"contents": [{"uri": VIEW, "mimeType": "text/html", "text": "<p>hi</p>"}]})
    with pytest.raises(ValueError, match="nothing"):
        resource_from(VIEW, {"contents": [{"uri": "ui://other", "mimeType": APP_MIME, "text": "x"}]})
    import base64

    blob = {"contents": [{"uri": VIEW, "mimeType": APP_MIME, "blob": base64.b64encode(b"<b>ok</b>").decode()}]}
    assert resource_from(VIEW, blob)["html"] == "<b>ok</b>"
    huge = {"content": [{"type": "text", "text": "x" * 300_000}], "structuredContent": {"a": 1}}
    assert result_for_view(huge)["_meta"] == {"spike/truncated": True}


async def test_the_client_announces_mcp_apps():
    client = McpClient(StdioTransport(sys.executable, [SERVER]), timeout_s=30)
    sent = []
    original = client.transport.send

    async def spy(message):
        sent.append(message)
        await original(message)

    client.transport.send = spy
    await client.start()
    init = next(m for m in sent if m.get("method") == "initialize")
    assert init["params"]["capabilities"]["extensions"][UI_EXTENSION] == {"mimeTypes": [APP_MIME]}
    result = await client.call_tool("get_price", {"symbol": "BTC"})
    assert result.raw["structuredContent"] == {"symbol": "BTC", "price": 50000}
    await client.close()


def add_app_connector(client) -> dict:
    r = client.post("/api/connectors", json={"id": "prices", "name": "Prices", "transport": "stdio",
                                             "command": sys.executable, "args": [SERVER]})
    assert r.status_code == 200, r.text
    view = client.put("/api/connectors/prices", json={"enabled": True}).json()
    assert view["status"] == "running", view["error"]
    return view


def test_app_only_tools_never_reach_the_model_and_results_carry_the_view(app):  # noqa: F811
    client, state, local = app
    view = add_app_connector(client)
    tools = {t["remote_name"]: t for t in view["tools"]}
    assert tools["refresh_price"]["visibility"] == ["app"] and tools["get_price"]["view"] == VIEW
    assert view["views"] == ["ui://prices/old", VIEW]
    model_tools = {t.name for t in state.connectors.tools()}
    assert "mcp__prices__get_price" in model_tools and "mcp__prices__refresh_price" not in model_tools
    client.put("/api/connectors/prices", json={"policy": "allow"})
    local._script = [call("mcp__prices__get_price", {"symbol": "BTC"}), text("50.000")]
    events = chat_events(client, "precio de BTC")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ui"] == {"kind": "mcp_app", "connector": "prices", "connector_name": "Prices",
                            "tool": "get_price", "uri": VIEW, "result": {
                                "content": [{"type": "text", "text": '{\n  "symbol": "BTC",\n  "price": 50000\n}'}],
                                "structuredContent": {"symbol": "BTC", "price": 50000}, "isError": False}}
    assert "mcp__prices__refresh_price" not in [t.name for t in local.requests[0].tools]
    stored = client.get(f"/api/conversations/{events[0]['id']}").json()
    assert any(ev.get("ui", {}).get("uri") == VIEW for m in stored["messages"] for ev in m["meta"].get("tools", []))


def test_views_are_served_only_when_declared_and_with_a_safe_policy(app):  # noqa: F811
    client, state, _ = app
    add_app_connector(client)
    page = client.get("/api/connectors/prices/view", params={"uri": VIEW}).json()
    assert "<h1 id=\"price\">" in page["html"] and page["prefers_border"] is True
    assert page["csp"] == {"connectDomains": ["https://api.example.com"], "resourceDomains": ["https://cdn.example.com"]}
    assert set(page["dropped"]) == {"http://127.0.0.1:8740", "https://localhost", "javascript:alert(1)"}
    assert "connect-src https://api.example.com" in page["policy"] and page["permissions"] == {}
    undeclared = client.get("/api/connectors/prices/view", params={"uri": "ui://prices/undeclared"})
    assert undeclared.status_code == 400 and "declares" in undeclared.json()["detail"]
    assert client.get("/api/connectors/nope/view", params={"uri": VIEW}).status_code == 404
    audit = client.get("/api/connectors-audit").json()
    assert audit[0]["event"] == "load" and audit[0]["sha256"] == page["sha256"]


def test_a_view_calls_only_its_own_app_tools_under_their_policy(app):  # noqa: F811
    client, state, _ = app
    add_app_connector(client)
    body = {"view": VIEW, "name": "refresh_price", "arguments": {"symbol": "BTC"}}
    asked = client.post("/api/connectors/prices/view/call", json=body)
    assert asked.status_code == 200 and asked.json() == {"needs_approval": True}  # "ask" by default
    done = client.post("/api/connectors/prices/view/call", json={**body, "approved": True}).json()
    assert done["result"]["structuredContent"] == {"symbol": "BTC", "price": 50100}
    model_only = client.post("/api/connectors/prices/view/call", json={**body, "name": "model_only",
                                                                        "arguments": {"text": "x"}, "approved": True})
    assert model_only.status_code == 403 and "only be called by the model" in model_only.json()["detail"]
    client.put("/api/settings", json={"tool_policies": {"mcp__prices__refresh_price": "deny"}})
    blocked = client.post("/api/connectors/prices/view/call", json={**body, "approved": True})
    assert blocked.status_code == 403 and "blocked" in blocked.json()["detail"]
    client.put("/api/settings", json={"tool_policies": {"mcp__prices__refresh_price": "allow"}})
    assert "result" in client.post("/api/connectors/prices/view/call", json=body).json()  # allowed: no question
    stranger = client.post("/api/connectors/prices/view/call", json={**body, "view": "ui://other/view"})
    assert stranger.status_code == 400  # a view this connector never declared
    assert client.post("/api/connectors/prices/view/call", json={**body, "name": "nope"}).status_code == 400
    read = client.post("/api/connectors/prices/view/read", json={"view": VIEW, "uri": "note://readme"}).json()
    assert json.loads(read["contents"][0]["text"]) == {"hello": "world"}
    client.post("/api/connectors/prices/view/event", json={"view": VIEW, "event": "open-link",
                                                            "detail": "https://example.com"})
    events = [(e["event"], e.get("decision")) for e in client.get("/api/connectors-audit").json()]
    assert events[:5] == [("open-link", None), ("resources/read", None), ("tools/call", "refused"),
                          ("tools/call", "refused"), ("tools/call", "allowed")]
    assert ("tools/call", "asked") in events and ("tools/call", "approved") in events
    assert ("tools/call", "allowed") in events


def test_view_context_reaches_the_model_as_data_for_one_turn(app):  # noqa: F811
    client, _, local = app
    local._script = lambda req: text("ok")
    with client.stream("POST", "/api/chat", json={"message": "¿qué veo?", "mode": "core", "view_context": [
            {"name": "Prices", "view": VIEW, "text": "BTC 50.100 USD"}]}) as r:
        r.read()
    system = local.requests[-1].messages[0].content
    assert "# What the user sees in app views" in system and "BTC 50.100 USD" in system
    assert "not instructions" in system
    with client.stream("POST", "/api/chat", json={"message": "otra", "mode": "core"}) as r:
        r.read()
    assert "BTC 50.100 USD" not in local.requests[-1].messages[0].content
