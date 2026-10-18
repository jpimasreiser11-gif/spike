"""A small Model Context Protocol client: tools over stdio and Streamable HTTP (JSON-RPC 2.0).

Only what SPIKE uses: the initialize handshake, tools/list, tools/call and resources/read (for MCP Apps, which SPIKE
announces with the `io.modelcontextprotocol/ui` extension). Requests a server sends to the client (sampling,
elicitation, roots) are answered "method not found"; ping is answered.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import os
import shutil
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from spike import __version__

PROTOCOL_VERSION = "2025-11-25"  # newest revision negotiated with the initialize handshake
UI_EXTENSION = "io.modelcontextprotocol/ui"  # MCP Apps (SEP-1865): tools whose results a ui:// view shows
APP_MIME = "text/html;profile=mcp-app"
OnMessage = Callable[[dict[str, Any]], Awaitable[None]]
# Variables a server process needs to start (find node/python, a home and temp dir); nothing else of SPIKE's
# environment, such as SPIKE_API_TOKEN or provider keys, reaches it.
PASSED_ENV = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC",
              "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "SHELL", "USER", "LOGNAME", "XDG_CACHE_HOME",
              "XDG_CONFIG_HOME", "XDG_DATA_HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy",
              "http_proxy", "no_proxy", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE")


class McpError(RuntimeError):
    """A connection or protocol failure; the message is safe to show."""


@dataclass
class CallResult:
    text: str
    is_error: bool
    raw: dict[str, Any] | None = field(default=None, compare=False)  # the whole CallToolResult, for an MCP App view


class Transport(ABC):
    on_closed: Callable[[str], None] | None = None  # set by the client: the server went away, with the reason

    @abstractmethod
    async def start(self, on_message: OnMessage) -> None: ...

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    def diagnostics(self) -> str:
        return ""


class StdioTransport(Transport):
    """Runs the server as a child process; one JSON-RPC message per line on stdin/stdout."""

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None, cwd: str | None = None):
        self.command, self.args, self.cwd = command, args, cwd
        self.env = {k: os.environ[k] for k in PASSED_ENV if k in os.environ} | (env or {})
        self.proc: asyncio.subprocess.Process | None = None
        self._tasks: list[asyncio.Task] = []
        self._stderr: deque[str] = deque(maxlen=40)

    async def start(self, on_message: OnMessage) -> None:
        exe = shutil.which(self.command, path=self.env.get("PATH")) or self.command
        try:
            self.proc = await asyncio.create_subprocess_exec(
                exe, *self.args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=self.env, cwd=self.cwd, limit=16 * 1024 * 1024)
        except OSError as exc:
            raise McpError(f"cannot start '{self.command}': {exc.strerror or exc}") from exc

        async def read_stdout() -> None:
            assert self.proc and self.proc.stdout
            while line := await self.proc.stdout.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # servers must not print anything else on stdout; tolerate it
                if isinstance(message, dict):
                    await on_message(message)
            with contextlib.suppress(TimeoutError):  # let the last stderr lines arrive: they explain the exit
                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=1)
            if self.on_closed:
                self.on_closed(f"the server process exited{self._tail()}")

        async def read_stderr() -> None:
            assert self.proc and self.proc.stderr
            while line := await self.proc.stderr.readline():
                self._stderr.append(line.decode(errors="replace").rstrip())

        stderr_task = asyncio.create_task(read_stderr())
        self._tasks = [asyncio.create_task(read_stdout()), stderr_task]

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def send(self, message: dict[str, Any]) -> None:
        if not self.running():
            raise McpError(f"the server process exited{self._tail()}")
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        try:
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise McpError(f"the server process exited{self._tail()}") from exc

    def _tail(self) -> str:
        return (": " + " | ".join(list(self._stderr)[-3:])) if self._stderr else ""

    def diagnostics(self) -> str:
        return "\n".join(self._stderr)

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(Exception):
                assert self.proc.stdin
                self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=3)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        self.proc.kill()
        for task in self._tasks:
            task.cancel()


class HttpTransport(Transport):
    """Streamable HTTP: every message is a POST; the answer is JSON or an event stream."""

    def __init__(self, url: str, headers: dict[str, str] | None = None, client: httpx.AsyncClient | None = None):
        self.url, self.headers = url, dict(headers or {})
        self.session_id: str | None = None
        self.protocol: str | None = None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15))
        self._on_message: OnMessage | None = None

    async def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **self.headers}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        return headers

    async def send(self, message: dict[str, Any]) -> None:
        assert self._on_message
        try:
            async with self._client.stream("POST", self.url, json=message, headers=self._headers()) as response:
                if response.status_code in (401, 403):
                    raise McpError(f"the server refused the credentials (HTTP {response.status_code})")
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")[:300]
                    raise McpError(f"HTTP {response.status_code}: {body}")
                self.session_id = response.headers.get("mcp-session-id", self.session_id)
                kind = response.headers.get("content-type", "")
                if "text/event-stream" in kind:
                    data: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            await self._dispatch("\n".join(data))
                            data = []
                    if data:
                        await self._dispatch("\n".join(data))
                elif "json" in kind:
                    await self._dispatch((await response.aread()).decode())
        except httpx.HTTPError as exc:
            raise McpError(f"cannot reach {self.url}: {exc.__class__.__name__}") from exc

    async def _dispatch(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        for message in payload if isinstance(payload, list) else [payload]:
            if isinstance(message, dict):
                await self._on_message(message)  # type: ignore[misc]

    async def close(self) -> None:
        if self.session_id:
            with contextlib.suppress(Exception):
                await self._client.delete(self.url, headers=self._headers(), timeout=5)
        await self._client.aclose()


class McpClient:
    def __init__(self, transport: Transport, timeout_s: float = 120.0):
        self.transport = transport
        self.timeout_s = timeout_s
        self.server_info: dict[str, Any] = {}
        self.tools_changed = False
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._sends: set[asyncio.Task] = set()

    async def start(self) -> dict[str, Any]:
        self.transport.on_closed = self._closed
        await self.transport.start(self._on_message)
        result = await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"extensions": {UI_EXTENSION: {"mimeTypes": [APP_MIME]}}},
            "clientInfo": {"name": "spike", "version": __version__},
        })
        if isinstance(self.transport, HttpTransport):
            self.transport.protocol = result.get("protocolVersion") or PROTOCOL_VERSION
        self.server_info = result
        await self.notify("notifications/initialized")
        return result

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        message = {"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})}
        # HTTP answers arrive while the POST is still open, so the send runs beside the wait
        send = asyncio.create_task(self.transport.send(message))
        self._sends.add(send)
        send.add_done_callback(self._sends.discard)
        timeout = McpError(f"'{method}' got no answer in {self.timeout_s:.0f} s")
        try:
            done, _ = await asyncio.wait({send, future}, timeout=self.timeout_s, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise timeout
            if future in done:
                response = future.result()
            else:
                if send.exception():
                    raise send.exception()  # type: ignore[misc]
                try:
                    response = await asyncio.wait_for(future, timeout=self.timeout_s)
                except TimeoutError as exc:
                    raise timeout from exc
        finally:
            self._pending.pop(rid, None)
        if "error" in response:
            err = response["error"] or {}
            raise McpError(str(err.get("message") or err))
        return response.get("result") or {}

    def _closed(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError(reason))

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self.transport.send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    async def _on_message(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            future = self._pending.get(message["id"])
            if future and not future.done():
                future.set_result(message)
        elif "method" in message and "id" in message:  # a request from the server
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
            if message["method"] == "ping":
                reply["result"] = {}
            else:
                reply["error"] = {"code": -32601, "message": f"SPIKE does not support '{message['method']}'"}
            task = asyncio.create_task(self.transport.send(reply))
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)
        elif message.get("method") == "notifications/tools/list_changed":
            self.tools_changed = True

    async def list_tools(self) -> list[dict[str, Any]]:
        tools, cursor = [], None
        for _ in range(100):
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += [t for t in result.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self.tools_changed = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallResult:
        result = await self.request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for item in result.get("content") or []:
            kind = item.get("type")
            if kind == "text":
                parts.append(str(item.get("text", "")))
            elif kind == "resource":
                res = item.get("resource") or {}
                parts.append(str(res.get("text") or f"[resource {res.get('uri', '')}]"))
            elif kind == "resource_link":
                parts.append(f"[resource {item.get('uri', '')}]")
            else:
                parts.append(f"[{kind} content omitted]")
        if not parts and result.get("structuredContent") is not None:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        return CallResult(text="\n".join(parts), is_error=bool(result.get("isError")), raw=result)

    async def read_resource(self, uri: str) -> dict[str, Any]:
        return await self.request("resources/read", {"uri": uri})

    async def close(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        await self.transport.close()
