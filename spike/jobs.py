"""An in-process queue for explicitly requested heavy work; admission leaves a RAM floor free.

Callers pass factories, never running coroutines: waiting jobs allocate no model or renderer. Cancellation holds
its slot until the coroutine's cleanup finishes. Callbacks must await their subprocess cleanup and must not detach
threads. Jobs are session-local; restarting the app never silently restarts training or evaluations.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import psutil

KINDS = {"render", "eval", "indexing", "training"}


class JobQueue:
    def __init__(self, limit: int = 1, ram_floor: int = 2 * 1024**3,
                 available: Callable[[], int] | None = None, poll: float = 0.25):
        if limit < 1 or ram_floor < 0:
            raise ValueError("invalid queue limits")
        self.limit, self.ram_floor, self.poll = limit, ram_floor, poll
        self.available = available or (lambda: psutil.virtual_memory().available)
        self._slots = asyncio.Semaphore(limit)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._closed = False
        self._owners: set[asyncio.Task] = set()

    def submit(self, kind: str, work: Callable[[], Awaitable[Any]]) -> str:
        if self._closed or kind not in KINDS:
            raise ValueError("queue closed or unknown job kind")
        jid = uuid.uuid4().hex
        row = {"id": jid, "kind": kind, "status": "queued", "created": time.time()}
        self._jobs[jid] = row

        async def run():
            try:
                async with self._slots:
                    while self.available() < self.ram_floor:
                        await asyncio.sleep(self.poll)
                    row["status"] = "running"
                    self._owners.add(asyncio.current_task())
                    try:
                        value = await work()
                    finally:
                        self._owners.discard(asyncio.current_task())
                    row["status"] = "completed"
                    return value
            except asyncio.CancelledError:
                row["status"] = "cancelled"
                raise
            except Exception:
                row["status"] = "failed"  # exception text may contain paths, credentials or document text
                raise
            finally:
                row["finished"] = time.time()

        task = asyncio.create_task(run())
        self._tasks[jid] = task
        # Background callers need no await; retrieve exceptions to avoid logging their potentially private detail.
        def finished(task):
            if task.cancelled():
                row["status"] = "cancelled"
                row["finished"] = time.time()
            else:
                task.exception()

        task.add_done_callback(finished)
        return jid

    async def wait(self, jid: str) -> Any:
        return await self._tasks[jid]

    async def execute(self, kind: str, work: Callable[[], Awaitable[Any]]) -> Any:
        if asyncio.current_task() in self._owners:
            return await work()
        return await self.wait(self.submit(kind, work))

    def list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._jobs.values()]

    def cancel(self, jid: str) -> bool:
        task = self._tasks.get(jid)
        if task is None:
            return False
        if not task.done() and self._jobs[jid]["status"] != "cancelling":
            self._jobs[jid]["status"] = "cancelling"
            if not task.cancelling():
                task.cancel()
        return True

    async def close(self) -> None:
        self._closed = True
        for jid in self._tasks:
            self.cancel(jid)
        await asyncio.gather(*(task for task in self._tasks.values() if not task.done()), return_exceptions=True)
        for row in self._jobs.values():
            if row["status"] == "cancelling":  # cancelled before the coroutine first ran
                row["status"] = "cancelled"
