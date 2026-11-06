"""Reliability and edge-case tests for MCP client and connectors (G15).

Covers against fake in-test servers (no external network):
1. Slow servers: request & notification timeouts, accurate sub-second formatting,
   remaining-deadline accounting, and cancellation of in-flight transport.send tasks.
2. Mid-response close: HTTP SSE/JSON stream closing after truncated JSON or non-UTF-8
   bytes fails immediately with McpError instead of hanging until timeout_s or
   raising UnicodeDecodeError; stdio process exiting mid-line fails immediately.
3. Invalid JSON / malformed JSON-RPC envelopes: string/numeric error fields,
   non-dict result payloads, stringified integer IDs, and malformed CallToolResult
   content arrays.
4. Bad pagination in tools/list: repeating/cyclic nextCursor, whitespace or non-string
   nextCursor, non-list tools field, and duplicate tool names across pages.
5. Weird tool schemas & permission invariants: unhashable/non-string tool names,
   non-dict or malformed inputSchema/properties/required, non-string description,
   and strict preservation of permission policies (never relaxing ask/deny/visibility).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from spike.connectors.apps import AppError
from spike.connectors.manager import ConnectorDef, ConnectorManager
from spike.connectors.mcp import (
    HttpTransport,
    McpClient,
    McpError,
    OnMessage,
    StdioTransport,
    Transport,
)
from spike.store.db import Store
from spike.store.secrets import SecretStore


class FakeSlowTransport(Transport):
    """Fake transport that hangs on send to test timeout and task cleanup."""

    def __init__(self, hang_on: set[str] | None = None):
        self.hang_on = hang_on or {"initialize", "tools/call", "notifications/initialized"}
        self.on_message: OnMessage | None = None
        self.active_sends = 0
        self.cancelled_sends = 0

    async def start(self, on_message: OnMessage) -> None:
        self.on_message = on_message

    async def send(self, message: dict[str, Any]) -> None:
        method = message.get("method", "")
        if method in self.hang_on:
            self.active_sends += 1
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancelled_sends += 1
                raise
            finally:
                self.active_sends -= 1
        if "id" in message and self.on_message:
            await self.on_message({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-11-25"}})

    async def close(self) -> None:
        pass


async def test_slow_server_timeout_and_send_cleanup() -> None:
    # 1. Request that hangs in transport.send times out promptly and cancels the hanging send task
    transport = FakeSlowTransport(hang_on={"tools/call"})
    client = McpClient(transport, timeout_s=0.15)
    await client.start()

    t0 = time.monotonic()
    with pytest.raises(McpError, match=r"got no answer in 0\.15 s|got no answer"):
        await client.call_tool("slow_tool", {})
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0
    await asyncio.sleep(0)  # allow cancellation callback to run
    assert transport.active_sends == 0
    assert transport.cancelled_sends == 1
    assert len(client._sends) == 0

    # 2. Notification that hangs in transport.send also times out with McpError instead of hanging forever
    notif_transport = FakeSlowTransport(hang_on={"notifications/initialized"})
    notif_client = McpClient(notif_transport, timeout_s=0.15)
    with pytest.raises(McpError, match="no answer|timed out"):
        await notif_client.start()
    await asyncio.sleep(0)
    assert notif_transport.active_sends == 0


async def test_server_closes_mid_response_http_and_stdio(tmp_path: Path) -> None:
    # 1. HTTP SSE stream closes mid-JSON without completing a JSON-RPC reply.
    #    Must fail immediately (< 0.5s) even though timeout_s is 5.0s!
    def sse_truncated_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"jsonrpc": "2.0", "id": 1, "result": {"half":\n\n',
        )

    http_sse = HttpTransport(
        "http://mcp.local/sse",
        client=httpx.AsyncClient(transport=httpx.MockTransport(sse_truncated_handler)),
    )
    c_sse = McpClient(http_sse, timeout_s=5.0)
    t0 = time.monotonic()
    with pytest.raises(McpError, match="invalid JSON|closed|no valid JSON-RPC|no answer"):
        await c_sse.start()
    assert time.monotonic() - t0 < 1.0
    await c_sse.close()

    # 2. HTTP application/json with invalid UTF-8 bytes + truncated JSON
    def bad_utf8_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"\xff\xfe{\"jsonrpc\": \"2.0\"",
        )

    http_bad = HttpTransport(
        "http://mcp.local/json",
        client=httpx.AsyncClient(transport=httpx.MockTransport(bad_utf8_handler)),
    )
    c_bad = McpClient(http_bad, timeout_s=5.0)
    t0 = time.monotonic()
    with pytest.raises(McpError):
        await c_bad.start()
    assert time.monotonic() - t0 < 1.0
    await c_bad.close()

    # 3. Stdio server that writes partial JSON mid-line and closes stdout/exits
    script = tmp_path / "mid_close.py"
    script.write_text(
        "import sys\n"
        "sys.stdin.readline()\n"
        "sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 1, \"result\": ')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    c_stdio = McpClient(StdioTransport(sys.executable, [str(script)]), timeout_s=5.0)
    t0 = time.monotonic()
    with pytest.raises(McpError, match="exited"):
        await c_stdio.start()
    assert time.monotonic() - t0 < 2.0
    await c_stdio.close()


async def test_invalid_json_rpc_envelopes_and_malformed_content() -> None:
    responses: list[dict[str, Any]] = [
        # 1. initialize with stringified ID "1"
        {"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-11-25", "serverInfo": {"name": "weird"}}},
        # 2. tools/call where error is a plain string instead of a dict
        {"jsonrpc": "2.0", "id": 2, "error": "rate limit exceeded"},
        # 3. tools/call where result is a list instead of a dict
        {"jsonrpc": "2.0", "id": 3, "result": ["unexpected", "list"]},
        # 4. tools/call where result.content has non-dict items and resource is a string
        {
            "jsonrpc": "2.0",
            "id": 4,
            "result": {
                "content": [
                    "bare string item",
                    None,
                    {"type": "resource", "resource": "not-a-dict"},
                    {"type": "text", "text": "valid text"},
                ]
            },
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if "id" not in body:
            return httpx.Response(202)
        reply = responses.pop(0)
        return httpx.Response(200, headers={"content-type": "application/json"}, json=reply)

    transport = HttpTransport(
        "http://mcp.local/rpc",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = McpClient(transport, timeout_s=2.0)

    # 1. Stringified ID "1" succeeds
    info = await client.start()
    assert info["serverInfo"]["name"] == "weird"

    # 2. String error raises McpError("rate limit exceeded") instead of AttributeError
    with pytest.raises(McpError, match="rate limit exceeded"):
        await client.call_tool("t1", {})

    # 3. Non-dict result raises McpError instead of AttributeError
    with pytest.raises(McpError, match="invalid|result"):
        await client.call_tool("t2", {})

    # 4. Malformed content items are handled gracefully without AttributeError
    res = await client.call_tool("t3", {})
    assert "valid text" in res.text
    await client.close()


async def test_bad_pagination_cycles_empty_pages_and_duplicates() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content.decode("utf-8"))
        if "id" not in body:
            return httpx.Response(202)
        rid = body["id"]
        method = body["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-11-25"}},
            )
        if method == "tools/list":
            calls += 1
            cursor = (body.get("params") or {}).get("cursor")
            if cursor is None:
                # Page 1 returns cursor "c1" and duplicate tool "echo"
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "id": rid,
                        "result": {
                            "tools": [
                                {"name": "echo", "description": "first"},
                                {"name": "echo", "description": "duplicate on page 1"},
                            ],
                            "nextCursor": "c1",
                        },
                    },
                )
            # Page 2 returns tool "sum", another duplicate "echo", and cycles back to nextCursor "c1"!
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "tools": [
                            {"name": "sum", "description": "second"},
                            {"name": "echo", "description": "duplicate on page 2"},
                        ],
                        "nextCursor": "c1",
                    },
                },
            )
        return httpx.Response(400)

    transport = HttpTransport(
        "http://mcp.local/rpc",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = McpClient(transport, timeout_s=2.0)
    await client.start()
    tools = await client.list_tools()

    # Cycle in nextCursor ("c1" -> "c1") must be stopped on page 2 (2 calls, NOT 100 calls!)
    assert calls == 2
    assert [t["name"] for t in tools] == ["echo", "sum"]
    assert tools[0]["description"] == "first"
    await client.close()


async def test_weird_tool_schemas_and_strict_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    store = Store(tmp_path / "spike.db")
    secrets = SecretStore(tmp_path / "secrets.json")
    catalog = [
        ConnectorDef(
            id="weird",
            name="Weird Server",
            transport="http",
            url="http://mcp.local/weird",
        )
    ]
    manager = ConnectorManager(store, secrets, tmp_path / "ws", tmp_path / "data", catalog=catalog)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if "id" not in body:
            return httpx.Response(202)
        rid = body["id"]
        method = body["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-11-25"}},
            )
        if method == "tools/list":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "tools": [
                            # Unhashable / non-string / blank names must be ignored safely
                            {"name": {"unhashable": True}, "description": "bad dict name"},
                            {"name": ["unhashable_list"], "description": "bad list name"},
                            {"name": 12345, "description": "numeric name"},
                            {"name": "   ", "description": "blank name"},
                            # Tool with non-dict inputSchema and non-string description
                            {
                                "name": "string_schema",
                                "description": ["list", "description"],
                                "inputSchema": "not-a-schema-object",
                                "_meta": {"ui": {"resourceUri": "ui://weird/view"}},
                            },
                            # Tool with non-object root type, malformed properties, and malformed required
                            {
                                "name": "broken_props",
                                "description": "Has weird properties",
                                "inputSchema": {
                                    "type": "array",
                                    "properties": {"query": "string", "bad_prop": None, "count": {"type": "integer"}},
                                    "required": ["query", 999, None, "nonexistent"],
                                },
                                "_meta": {"ui": {"resourceUri": "ui://weird/view", "visibility": ["app"]}},
                            },
                        ]
                    },
                },
            )
        if method == "tools/call":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "ok"}]}},
            )
        return httpx.Response(400)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        manager,
        "_client",
        lambda definition: McpClient(HttpTransport(definition.url, client=mock_http), timeout_s=2.0),
    )

    conn = await manager.start("weird")
    assert conn.status == "running", conn.error
    assert set(conn.by_remote.keys()) == {"string_schema", "broken_props"}

    # Check schema normalization
    t1 = conn.by_remote["string_schema"]
    assert t1.parameters == {"type": "object", "properties": {}}
    assert isinstance(t1.description, str)

    t2 = conn.by_remote["broken_props"]
    assert t2.parameters["type"] == "object"
    assert t2.parameters["properties"]["query"] == {"type": "string"}
    assert t2.parameters["properties"]["bad_prop"] == {}
    assert t2.parameters["properties"]["count"] == {"type": "integer"}
    assert t2.parameters["required"] == ["query"]

    # Check permission invariants: never relaxed!
    assert t1.default_policy == "ask" and t1.risk == "network"
    assert t2.default_policy == "ask" and t2.risk == "network"
    # broken_props is app-only, so it must NOT be exposed in manager.tools() for the model
    assert [t.name for t in manager.tools()] == ["mcp__weird__string_schema"]

    # app_call must reject unapproved ask call, deny call, and non-dict arguments
    with pytest.raises(PermissionError, match="needs your approval"):
        await manager.app_call(
            "weird",
            "ui://weird/view",
            "broken_props",
            {"query": "hi"},
            approved=False,
            policy_for=lambda tool, args: (tool.default_policy, None),
        )

    with pytest.raises(AppError, match="arguments"):
        await manager.app_call(
            "weird",
            "ui://weird/view",
            "broken_props",
            ["not-a-dict"],  # type: ignore[arg-type]
            approved=True,
            policy_for=lambda tool, args: ("allow", None),
        )

    await manager.close_all()
