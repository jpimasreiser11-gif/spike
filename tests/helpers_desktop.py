"""Test doubles for the desktop tests: a driver that only records what it is asked, a provider that serves fixture
answers, and a rig that wires them to the real service, guard and call log. No screen, no network, no program."""

from __future__ import annotations

import asyncio
import copy
import json
import struct
import zlib
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from spike.core.types import Capabilities, ProviderError
from spike.desktop.backends import EVERYTHING
from spike.desktop.driver import PNG_MAGIC, Availability, Driver, DriverError, Ran
from spike.desktop.service import DesktopService
from spike.desktop.settings import DEFAULTS
from spike.providers.base import Provider, ProviderConfig
from spike.providers.guard import GuardedProvider
from spike.store.db import Store

FIXTURES = Path(__file__).parent / "fixtures" / "desktop"
RESPONSES = json.loads((FIXTURES / "anthropic_responses.json").read_text(encoding="utf-8"))
REQUESTS = json.loads((FIXTURES / "anthropic_requests.json").read_text(encoding="utf-8"))


def reply(name: str) -> dict[str, Any]:
    """A fixture answer of the provider (a copy: the loop keeps what it is given)."""
    return copy.deepcopy(RESPONSES[name])


def action_reply(n: int, name: str, words: str = "", **args: Any) -> dict[str, Any]:
    """An answer asking for one action (`name` with `args`) after the model's `words`, with an id of its own."""
    content: list[dict[str, Any]] = [{"type": "text", "text": words}] if words else []
    content.append({"type": "tool_use", "id": f"toolu_{n:02d}", "name": name, "toolset_name": "computer", "input": args})
    return {"id": f"msg_{n:02d}", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": content, "stop_reason": "tool_use", "usage": {"input_tokens": 1000, "output_tokens": 50}}


def click_reply(n: int = 1, *, x: int = 100, y: int = 100, words: str = "") -> dict[str, Any]:
    """An answer asking for a left click at (x + n, y)."""
    return action_reply(n, "left_click", words, coordinate=[x + n, y])


@lru_cache(maxsize=32)
def png(width: int, height: int, shade: int = 200) -> bytes:
    """A real, tiny PNG of a flat grey: what the fake screen looks like."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + bytes([shade]) * width for _ in range(height))
    return (PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeDriver(Driver):
    """Records every action instead of doing it. `fail` maps an action ("click", "type", ...) to the message of the
    DriverError it raises; `secure` is what it says about the focused field."""

    backend = "fake"
    supports = EVERYTHING

    def __init__(self, screen: tuple[int, int] = (1024, 768), secure: bool | None = None,
                 fail: dict[str, str] | None = None):
        super().__init__(lambda *args: Ran(1))
        self.screen, self.secure, self.fail = screen, secure, dict(fail or {})
        self.calls: list[tuple[Any, ...]] = []
        self.captures = 0
        self.closed = False
        self.pointer = (10, 20)

    def screen_size(self) -> tuple[int, int]:
        return self.screen

    def capture(self, width: int, height: int) -> bytes:
        self.captures += 1
        return png(width, height, 100 + 50 * (self.captures % 3))

    def _do(self, name: str, *args: Any) -> None:
        if name in self.fail:
            raise DriverError(self.fail[name])
        self.calls.append((name, *args))

    def click(self, x, y, button="left", count=1, mods=()):
        self._do("click", x, y, button, count, tuple(mods))

    def move(self, x, y):
        self._do("move", x, y)

    def drag(self, x1, y1, x2, y2, mods=()):
        self._do("drag", x1, y1, x2, y2, tuple(mods))

    def scroll(self, x, y, direction, amount, mods=()):
        self._do("scroll", x, y, direction, amount, tuple(mods))

    def type_text(self, text):
        self._do("type", text)

    def key(self, combo, repeat=1):
        self._do("key", combo, repeat)

    def cursor_position(self):
        return self.pointer

    def secure_field_focused(self):
        return self.secure

    def close(self) -> None:
        self.closed = True

    def acted(self) -> list[tuple[Any, ...]]:
        return list(self.calls)


class FakeInner(Provider):
    """A provider with a computer-use API that answers from a list of fixture responses and keeps what it was sent.
    While `gate` is set it holds every answer back (a request that is still in flight)."""

    computer_use_adapter = "anthropic"

    def __init__(self, config: ProviderConfig, script: Sequence[dict[str, Any]]):
        super().__init__(config)
        self.script = list(script)
        self.payloads: list[dict[str, Any]] = []
        self.betas: list[list[str]] = []
        self.gate: asyncio.Event | None = None
        self.arrived = asyncio.Event()
        self.cancelled = False

    def default_capabilities(self) -> Capabilities:
        return Capabilities(native_tools=True, vision=True)

    async def stream(self, request):  # never used by a desktop task
        raise AssertionError("a desktop task must not use the chat stream")
        yield

    async def list_models(self) -> list[str]:
        return [self.config.model]

    async def send_raw(self, payload: dict[str, Any], *, beta: Sequence[str] = ()) -> dict[str, Any]:
        self.payloads.append(copy.deepcopy(payload))
        self.betas.append(list(beta))
        self.arrived.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if not self.script:
            raise ProviderError("the script has no more answers")
        return copy.deepcopy(self.script.pop(0))


def provider_config(**over: Any) -> ProviderConfig:
    values: dict[str, Any] = {"id": "claude", "kind": "anthropic", "name": "Claude", "base_url": "https://api.anthropic.com/v1",
                              "model": "claude-sonnet-5-5", "api_key": "sk-ant-test", "paid": True, "allow_paid": True,
                              "share_files": True}
    return ProviderConfig(**{**values, **over})


async def instant(_seconds: float) -> None:
    """In place of waiting for the screen to settle."""


class Rig:
    """The real service, guard, call log and task loop with a fake screen and a fake provider."""

    def __init__(self, tmp_path: Path, script: Sequence[dict[str, Any]], *, enabled: bool = True, max_steps: int = 20,
                 tool: str = "auto", driver: FakeDriver | None = None, limits: dict[str, Any] | None = None,
                 **config: Any):
        self.cfg = provider_config(**config)
        self.inner = FakeInner(self.cfg, script)
        self.store = Store(tmp_path / "rig.db")
        self.limits = dict(limits or {})
        self.guard = GuardedProvider(self.inner, self.store, lambda: dict(self.limits))
        self.driver = driver or FakeDriver()
        self.settings = {**DEFAULTS, "enabled": enabled, "provider_id": "claude", "max_steps": max_steps, "tool": tool}
        self.configs = [{"id": "claude", "name": "Claude", "kind": "anthropic", "model": self.cfg.model,
                         "base_url": self.cfg.base_url, "local": self.cfg.local}]
        self.service = DesktopService(lambda: self.settings, lambda pid: self.guard, lambda: self.configs, tmp_path,
                                      detect=lambda: (self.driver, Availability(True, "fake")))
        self.service.task_options = {"sleep": instant, "settle_s": 0.0}
        self.home = tmp_path

    @property
    def broker(self):
        return self.service.broker


Answer = str | tuple[str, int] | Callable[[Any, dict[str, Any]], Any] | None


async def play(rig: Rig, goal: str = "open the calculator", answers: Sequence[Answer] = (), *, timeout: float = 10.0,
               **start: Any):
    """Run a task to its end, answering each card that asks: with the next of `answers` (a decision, a pair of decision
    and N, or a function of the task and the card that returns one, or None after it dealt with the task itself),
    approve when there are none left. Returns the task and its events."""
    task = rig.service.start(goal, **start)
    queue, events = list(answers), []

    async def drive() -> None:
        async for ev in task.run():
            events.append(ev)
            if ev["type"] == "desktop_action" and not ev["auto"]:
                answer = queue.pop(0) if queue else "approve"
                if callable(answer):
                    answer = answer(task, ev)
                if answer is None:
                    continue
                name, n = (answer, 1) if isinstance(answer, str) else answer
                assert rig.broker.resolve(ev["id"], name, n) is not None

    await asyncio.wait_for(drive(), timeout)
    return task, events


def of_type(events: Sequence[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind]
