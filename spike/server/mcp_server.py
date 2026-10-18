"""SPIKE as an MCP server, so Claude Code, Cursor, Codex or any MCP client can ask SPIKE's specialists.

Tools: `ask_spike` (the orchestrator picks the specialists) and one `spike_<id>` per specialist. Transports: stdio
(`spike mcp`) and Streamable HTTP (`POST /mcp` on a running `spike serve`, same access rules as `/v1`). Like the
`/v1` API, calls get no memory and no connectors, and tools that need the user's approval are refused.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import threading
from typing import Any

from spike import __version__
from spike.server.state import AppState
from spike.tools.base import HeadlessBroker

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # newest first
CALLER_NOTE = ("The request comes from another AI agent through MCP. Answer for that agent: complete, precise and "
               "self-contained, in the language of the question.")
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class SpikeMcp:
    def __init__(self, state: AppState):
        self.state = state
        self.starting: asyncio.Task | None = None  # the local engine being started by `spike mcp --start-local`

    # ------------------------------------------------------------------ tools
    def tools(self) -> list[dict[str, Any]]:
        specialists = [s for s in self.state.catalog.specialists.values() if s.id != "core"]
        question = {"type": "string", "description": "the question or task, with everything needed to answer it"}
        context = {"type": "string", "description": "optional material to work from (text, data, code)"}
        output = {"type": "object", "properties": {"answer": {"type": "string"},
                                                   "specialists": {"type": "array", "items": {"type": "string"}}},
                  "required": ["answer", "specialists"]}
        tools = [{
            "name": "ask_spike",
            "title": "Ask SPIKE",
            "description": ("Ask SPIKE, a team of specialist models (" + ", ".join(s.name.replace("Spike ", "")
                            for s in specialists) + ") coordinated by an orchestrator that picks one or several and "
                            "merges their answers. Runs on the user's computer with the models they configured."),
            "inputSchema": {"type": "object", "properties": {
                "question": question, "context": context,
                "specialist": {"type": "string", "enum": ["auto", *[s.id for s in specialists]],
                               "description": "who answers; auto lets SPIKE choose (default)"},
            }, "required": ["question"]},
            "outputSchema": output,
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }]
        for spec in specialists:
            tools.append({
                "name": f"spike_{spec.id}", "title": spec.name,
                "description": f"Ask SPIKE's {spec.name} specialist ({spec.domain}). {spec.description}",
                "inputSchema": {"type": "object", "properties": {"question": question, "context": context},
                                "required": ["question"]},
                "outputSchema": output,
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            })
        return tools

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """A tools/call result; failures of the run are results with isError, as MCP asks."""
        if name == "ask_spike":
            mode = str(arguments.get("specialist") or "auto")
        elif name.startswith("spike_") and name[6:] in self.state.catalog.specialists and name != "spike_core":
            mode = name[6:]
        else:
            raise KeyError(name)
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return _error_result("'question' is required")
        if mode != "auto" and mode not in self.state.catalog.specialists:
            return _error_result(f"unknown specialist '{mode}'")
        context = arguments.get("context")
        text = question.strip() + (f"\n\n# Material\n{context.strip()}" if isinstance(context, str) and
                                   context.strip() else "")
        if self.starting:
            await asyncio.shield(self.starting)  # its own failure is reported by the run below
        state = self.state
        await state.ensure_adapters()
        orchestrator = state.orchestrator(broker=HeadlessBroker(state.broker))
        opts = state.options(mode)
        opts.app_instructions = CALLER_NOTE
        answer, specialists, error = "", [], None
        try:
            async for ev in orchestrator.run([], text, opts):
                if ev["type"] == "delta" and "subtask" not in ev:
                    answer += ev["text"]
                elif ev["type"] == "done":
                    specialists, error = ev["specialists"], ev.get("error")
        except Exception as exc:  # a provider that cannot be reached, for example
            error = f"{exc.__class__.__name__}: {exc}"
        if error:
            hint = (" Is SPIKE's local engine running? Start the app with `spike serve`, or run this server as "
                    "`spike mcp --start-local`.") if "connect" in error.lower() else ""
            return _error_result(f"SPIKE could not answer: {error}.{hint}")
        return {"content": [{"type": "text", "text": answer}],
                "structuredContent": {"answer": answer, "specialists": specialists}, "isError": False}

    # ------------------------------------------------------------------ JSON-RPC
    async def handle(self, message: Any) -> dict[str, Any] | None:
        """One JSON-RPC message in, its response out (None for notifications and responses)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return rpc_error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        rid, method = message.get("id"), message.get("method")
        if method is None or rid is None:
            return None  # a notification (notifications/initialized, cancelled) or a response: nothing to answer
        params = message.get("params") or {}
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                return rpc_result(rid, {
                    "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "spike", "title": "SPIKE", "version": __version__},
                    "instructions": ("SPIKE's specialists answer questions in their domain; ask_spike lets SPIKE "
                                     "choose. Answers come from the user's own models and can be slow on a CPU."),
                })
            if method == "ping":
                return rpc_result(rid, {})
            if method == "tools/list":
                return rpc_result(rid, {"tools": self.tools()})
            if method == "tools/call":
                name, arguments = params.get("name"), params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    return rpc_error(rid, INVALID_PARAMS, "'arguments' must be an object")
                try:
                    return rpc_result(rid, await self.call(str(name), arguments))
                except KeyError:
                    return rpc_error(rid, INVALID_PARAMS, f"unknown tool '{name}'")
            return rpc_error(rid, METHOD_NOT_FOUND, f"method not found: {method}")
        except Exception as exc:  # never leave a request unanswered
            log.exception("mcp: %s failed", method)
            return rpc_error(rid, -32603, f"internal error: {exc.__class__.__name__}")


def rpc_result(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _error_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


MAX_MESSAGE = 16 * 1024 * 1024


def _read_stdin(loop: asyncio.AbstractEventLoop, lines: asyncio.Queue[bytes]) -> None:
    """Hand stdin's lines to the loop, then b"" at the end. A thread, because asyncio cannot read a pipe or console
    stdin on Windows (the proactor loop refuses its handle)."""
    try:
        for line in iter(sys.stdin.buffer.readline, b""):
            loop.call_soon_threadsafe(lines.put_nowait, line)
    except (OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(RuntimeError):  # the loop already closed
            loop.call_soon_threadsafe(lines.put_nowait, b"")


def _write(message: dict[str, Any]) -> None:
    """One message per line, always UTF-8 (the console code page on Windows could not encode every answer)."""
    sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


async def serve_stdio(state: AppState, start_local: bool = False) -> None:
    """Newline-delimited JSON-RPC on stdin/stdout; logs go to stderr only."""
    server = SpikeMcp(state)
    lines: asyncio.Queue[bytes] = asyncio.Queue()
    threading.Thread(target=_read_stdin, args=(asyncio.get_running_loop(), lines), daemon=True,
                     name="spike-mcp-stdin").start()
    write_lock = asyncio.Lock()
    tasks: set[asyncio.Task] = set()

    async def answer(message: Any) -> None:
        response = await server.handle(message)
        if response is not None:
            async with write_lock:
                _write(response)

    async def start_engine() -> None:
        try:
            await state.start_runtime()
        except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
            print(f"spike mcp: the local engine did not start: {exc}", file=sys.stderr)

    if start_local:  # in the background: clients give a server a few seconds to answer `initialize`
        server.starting = asyncio.create_task(start_engine())
    try:
        while line := await lines.get():
            line = line.strip()
            if not line:
                continue
            try:
                if len(line) > MAX_MESSAGE:
                    raise ValueError("message too long")
                message = json.loads(line)
            except ValueError:
                await answer_raw(rpc_error(None, PARSE_ERROR, "invalid JSON"), write_lock)
                continue
            task = asyncio.create_task(answer(message))  # a long tools/call must not block ping
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if server.starting:
            server.starting.cancel()
            await asyncio.gather(server.starting, return_exceptions=True)
            await state.stop_runtime()
        await state.close()


async def answer_raw(response: dict[str, Any], lock: asyncio.Lock) -> None:
    async with lock:
        _write(response)
