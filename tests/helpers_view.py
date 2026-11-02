"""A fake Spike View for the recorder and replay tests: what a replay needs from the browser, without a browser."""

from __future__ import annotations

import asyncio
from typing import Any

from spike.connectors import browser
from spike.tools.base import Review


class FakeBackend:
    """Whether View runs, the guard's review of a call, a tool the user turned off, and the call itself."""

    def __init__(self, domains=None, unknown="ask", results=None, blocked=(), running=True, delay=0.0):
        self.settings = {"domains": dict(domains or {}), "unknown": unknown}
        self.results, self.blocked_tools, self.running, self.delay = results or {}, set(blocked), running, delay
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.allowed: list[str] = []

    def available(self) -> bool:
        return self.running

    def review(self, remote: str, args: dict[str, Any]) -> Review | None:
        return browser.review(remote, args, self.settings)

    def blocked(self, remote: str) -> bool:
        return remote in self.blocked_tools

    def allow_domain(self, domain: str) -> None:
        self.allowed.append(domain)
        self.settings["domains"][domain] = "allow"

    async def call(self, remote: str, args: dict[str, Any]) -> tuple[bool, str]:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append((remote, args))
        return self.results.get(remote, (True, "ok"))
