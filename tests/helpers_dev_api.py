"""An in-process ASGI client that streams: the test can read the first events of a Dev turn, answer a permission card
through a second request on the same event loop, and then read the rest. httpx's ASGI transport and Starlette's
TestClient both buffer a whole response, which would wait for an answer nobody can give."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

LOCAL = ("127.0.0.1", 50000)


class Reply:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]):
        self.status, self.body, self.headers = status, body, headers

    def json(self) -> Any:
        return json.loads(self.body)


class Live:
    """A response being read as it arrives."""

    def __init__(self, task: asyncio.Task, queue: asyncio.Queue, disconnect: asyncio.Event):
        self.task, self.queue, self.disconnect = task, queue, disconnect
        self.status = 0
        self.headers: dict[str, str] = {}
        self._buffer, self._ended, self.seen = "", False, []

    async def next(self, timeout: float = 20) -> dict | None:
        """The next server-sent event, or None when the response ended."""
        while True:
            if "\n\n" in self._buffer:
                block, self._buffer = self._buffer.split("\n\n", 1)
                data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
                if data:
                    ev = json.loads("\n".join(data))
                    self.seen.append(ev)
                    return ev
                continue
            if self._ended:
                return None
            msg = await asyncio.wait_for(self.queue.get(), timeout)
            if msg["type"] == "http.response.start":
                self.status = msg["status"]
                self.headers = {k.decode(): v.decode() for k, v in msg["headers"]}
            else:
                self._buffer += msg.get("body", b"").decode("utf-8")
                self._ended = not msg.get("more_body", False)

    async def until(self, kind: str, timeout: float = 20) -> dict:
        while (ev := await self.next(timeout)) is not None:
            if ev["type"] == kind:
                return ev
        raise AssertionError(f"the stream ended without a '{kind}' event; saw {[e['type'] for e in self.seen]}")

    async def rest(self, timeout: float = 20) -> list[dict]:
        out = []
        while (ev := await self.next(timeout)) is not None:
            out.append(ev)
        return out

    async def drop(self) -> None:
        """The browser closes the connection."""
        self.disconnect.set()
        await asyncio.wait_for(self.task, 10)


class Asgi:
    def __init__(self, app, client: tuple[str, int] = LOCAL):
        self.app, self.client = app, client

    def start(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Live:
        raw = json.dumps(body).encode() if body is not None else b""
        parts = urlsplit(path)
        sent, disconnect, queue = False, asyncio.Event(), asyncio.Queue()

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            await queue.put(message)

        head = {"host": "127.0.0.1", "content-type": "application/json", "content-length": str(len(raw)),
                **(headers or {})}
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
                 "headers": [(k.lower().encode(), v.encode()) for k, v in head.items()], "client": self.client,
                 "server": ("127.0.0.1", 80), "scheme": "http", "root_path": ""}
        task = asyncio.get_running_loop().create_task(self.app(scope, receive, send))
        return Live(task, queue, disconnect)

    async def request(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Reply:
        live = self.start(method, path, body, headers)
        chunks = []
        while True:
            msg = await asyncio.wait_for(live.queue.get(), 20)
            if msg["type"] == "http.response.start":
                live.status = msg["status"]
                live.headers = {k.decode(): v.decode() for k, v in msg["headers"]}
            else:
                chunks.append(msg.get("body", b""))
                if not msg.get("more_body", False):
                    break
        live.disconnect.set()
        await asyncio.wait_for(live.task, 10)
        return Reply(live.status, b"".join(chunks), live.headers)

    async def get(self, path: str, **kw) -> Reply:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, body: Any = None, **kw) -> Reply:
        return await self.request("POST", path, body if body is not None else {}, **kw)

    async def delete(self, path: str, **kw) -> Reply:
        return await self.request("DELETE", path, **kw)
