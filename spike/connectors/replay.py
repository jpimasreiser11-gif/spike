"""Replay of a recorded Spike View script (A16), one step at a time, under the same browser rules as live use.

The replay never decides for the user. Before a step it asks when:
- the step may submit something: a typing step with submit, pressing Enter, a click on a button that sends, buys,
  signs in, deletes or publishes (the guard's own words, `browser.review`), or any step the recording marked as
  submitting. The answer is for that one step only: there is no "always";
- the step opens a page on a domain the browser settings do not allow (the guard's rule: allowed domains open, other
  ones ask unless the user chose to open them). A domain the user blocked is never opened: the step can only be
  skipped;
- a step needs a secret (a password field): the text is asked for and used for that one call, never kept;
- the user chose step mode: before every step.
A step that fails asks what to do (retry, skip or stop). Stop ends the replay at once, even in the middle of a step;
a question nobody answers ends it after ANSWER_TIMEOUT_S. Only one replay runs at a time.

What it runs is the connector's own tools (`browser_navigate`, `browser_click`, `browser_type`, `browser_select_option`,
`browser_press_key`) with the selector the recording kept; nothing else can be in a script (see `scripts.py`). A tool the
user turned off in Settings is not used. A click on a link that opens another domain is not seen coming, like in live
use; the browser's own blocked-domain list still applies to it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

from spike.connectors import browser
from spike.connectors.scripts import ScriptError, ScriptStore, describe, selector_of, target_name
from spike.tools.base import Review

ANSWER_TIMEOUT_S = 1800.0
MODES = ("auto", "step")
ACTIVE = ("running", "waiting")
DETAIL = 300


class ReplayError(Exception):
    """The replay cannot start: `code` is busy, off, not_found, invalid or mode."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class Backend(Protocol):
    """What a replay needs from Spike View."""

    def available(self) -> bool: ...
    def review(self, remote: str, args: dict[str, Any]) -> Review | None: ...
    def blocked(self, remote: str) -> bool: ...
    def allow_domain(self, domain: str) -> None: ...
    async def call(self, remote: str, args: dict[str, Any]) -> tuple[bool, str]: ...


class ConnectorBackend:
    """The running Playwright connector: its tools' own review (domains and submissions) and its client."""

    def __init__(self, manager: Any, broker: Any, connector: str = browser.CONNECTOR):
        self.manager, self.broker, self.connector = manager, broker, connector

    def connection(self) -> Any:
        conn = self.manager.connections.get(self.connector)
        return conn if conn is not None and conn.status == "running" and conn.client is not None else None

    def available(self) -> bool:
        return self.connection() is not None

    def tool(self, remote: str) -> Any:
        conn = self.connection()
        return conn.by_remote.get(remote) if conn is not None else None

    def review(self, remote: str, args: dict[str, Any]) -> Review | None:
        tool = self.tool(remote)
        return tool.review(args) if tool is not None else browser.review(remote, args, self.manager.browser_settings())

    def blocked(self, remote: str) -> bool:
        """The connector has no such tool, or the user turned it off."""
        tool = self.tool(remote)
        return tool is None or self.broker.policy_for(tool) == "deny"

    def allow_domain(self, domain: str) -> None:
        self.manager.set_domain(domain, "allow")

    async def call(self, remote: str, args: dict[str, Any]) -> tuple[bool, str]:
        conn = self.connection()
        if conn is None:
            return False, "Spike View is not running"
        result = await conn.client.call_tool(remote, args)
        return (not result.is_error), result.text


class Stop(Exception):
    """The user ended the replay (or nobody answered)."""

    def __init__(self, reason: str = "user"):
        super().__init__(reason)
        self.reason = reason


def to_call(step: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """(tool, arguments, problem) for a step; a problem is `no_target` when it has no selector to act on."""
    action = step["action"]
    if action == "navigate":
        return "browser_navigate", {"url": step["url"]}, ""
    if action == "press":
        return "browser_press_key", {"key": step["key"]}, ""
    selector = selector_of(step["target"])
    element = (step.get("element") or target_name(step) or "element")[:200]
    base = {"element": element, "target": selector or ""}
    if action == "click":
        return "browser_click", {**base, **({"doubleClick": True} if step.get("double") else {})}, \
            "" if selector else "no_target"
    if action == "type":
        args = {**base, "text": step.get("text", ""), **({"submit": True} if step.get("submit") else {})}
        return "browser_type", args, "" if selector else "no_target"
    return "browser_select_option", {**base, "values": list(step["values"])}, "" if selector else "no_target"


class Replayer:
    def __init__(self, backend: Backend, store: ScriptStore):
        self.backend, self.store = backend, store
        self.state = "idle"  # idle | running | waiting | done | stopped | error
        self.reason = ""
        self.mode = "auto"
        self.script: dict[str, Any] | None = None
        self.sid = ""
        self.rows: list[dict[str, Any]] = []
        self.index = 0
        self.question: dict[str, Any] | None = None
        self.task: asyncio.Task[None] | None = None
        self.waiting: tuple[str, list[str], asyncio.Future[tuple[str, str | None]]] | None = None

    # ------------------------------------------------------------------ control
    def start(self, sid: str, mode: str = "auto") -> dict[str, Any]:
        if self.state in ACTIVE:
            raise ReplayError("a replay is already running", "busy")
        if mode not in MODES:
            raise ReplayError(f"mode must be one of {', '.join(MODES)}", "mode")
        if not self.backend.available():
            raise ReplayError("Spike View is not running", "off")
        try:
            script = self.store.get(sid)
        except ScriptError as exc:
            raise ReplayError(str(exc), exc.code) from exc
        self.script, self.sid, self.mode, self.index, self.reason, self.question = script, sid, mode, 0, "", None
        self.rows = [{"n": i, **describe(s), "status": "pending"} for i, s in enumerate(script["steps"])]
        self.state = "running"
        self.task = asyncio.get_running_loop().create_task(self.run())
        return self.status()

    def stop(self) -> bool:
        """End the replay now. False when none is running."""
        if self.state not in ACTIVE:
            return False
        self.finish("stopped", "user")
        if self.task is not None:
            self.task.cancel()
        return True

    def finish(self, state: str, reason: str = "") -> None:
        if self.state in ACTIVE:
            self.state, self.reason, self.question = state, reason, None

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "mode": self.mode,
                "script": {"id": self.sid, "name": self.script["name"]} if self.script else None,
                "index": self.index, "total": len(self.rows), "steps": [dict(r) for r in self.rows],
                "question": dict(self.question) if self.question else None}

    def answer(self, question: str, decision: str, value: str | None = None) -> bool:
        """The user's answer to the question the replay is waiting on; False when it is not the one it asks (or the
        answer is not one of its options)."""
        waiting = self.waiting
        if waiting is None or waiting[0] != question or decision not in waiting[1] or waiting[2].done():
            return False
        if decision == "provide" and not isinstance(value, str):
            return False
        waiting[2].set_result((decision, value if decision == "provide" else None))
        return True

    # ------------------------------------------------------------------ the run
    async def ask(self, kind: str, code: str, options: list[str], **info: Any) -> tuple[str, str | None]:
        """Wait for the user. Raises Stop when they stop, or when the question times out."""
        qid = f"q_{uuid.uuid4().hex[:10]}"
        future: asyncio.Future[tuple[str, str | None]] = asyncio.get_running_loop().create_future()
        self.question = {"id": qid, "kind": kind, "code": code, "step": self.index, "domain": None, "detail": "",
                         "reason": "", **info, "options": options}
        self.waiting, self.state = (qid, options, future), "waiting"
        try:
            decision, value = await asyncio.wait_for(future, ANSWER_TIMEOUT_S)
        except TimeoutError as exc:
            raise Stop("no_answer") from exc
        finally:
            self.waiting, self.question = None, None
            if self.state == "waiting":
                self.state = "running"
        if decision == "stop":
            raise Stop("user")
        return decision, value

    async def run(self) -> None:
        try:
            assert self.script is not None
            for i, step in enumerate(self.script["steps"]):
                self.index = i
                if self.mode == "step":
                    await self.ask("step", "step", ["next", "stop"])
                self.rows[i]["status"] = await self.step(step)
            self.index = len(self.rows)
            self.finish("done")
        except Stop as stop:
            self.finish("stopped", stop.reason)
        except asyncio.CancelledError:
            self.finish("stopped", "user")
            raise
        except Exception:  # noqa: BLE001 - never leave the app waiting on a replay that crashed
            self.finish("error", "internal")

    async def step(self, step: dict[str, Any]) -> str:
        """Run one step after the questions it needs; returns `done` or `skipped`."""
        remote, args, problem = to_call(step)
        if problem:
            self.rows[self.index]["status"] = "failed"
            await self.ask("failed", problem, ["skip", "stop"])
            return "skipped"
        if self.backend.blocked(remote):
            await self.ask("blocked", "tool_blocked", ["skip", "stop"], reason=f"{remote} is turned off")
            return "skipped"
        if step["action"] == "type" and step.get("secret"):  # the text is asked for now, used for this call only
            decision, value = await self.ask("secret", "secret", ["provide", "skip", "stop"])
            if decision == "skip" or not value:
                return "skipped"
            args["text"] = value
            value = None
        while True:
            if not await self.allowed(step, remote, args):
                return "skipped"
            try:
                ok, text = await self.backend.call(remote, args)
            except Exception as exc:  # noqa: BLE001 - a browser that went away is a failed step, not a crashed replay
                ok, text = False, f"{exc.__class__.__name__}: {str(exc)[:DETAIL]}"
            if ok:
                return "done"
            self.rows[self.index]["status"] = "failed"
            decision, _ = await self.ask("failed", "failed", ["retry", "skip", "stop"], detail=text.strip()[:DETAIL])
            self.rows[self.index]["status"] = "pending"
            if decision == "skip":
                return "skipped"

    async def allowed(self, step: dict[str, Any], remote: str, args: dict[str, Any]) -> bool:
        """Ask what the guard asks for this call (or what the recording marked); False when the user skips it."""
        review = self.backend.review(remote, args)
        if review is not None and review.policy == "deny":
            await self.ask("blocked", review.code or "blocked", ["skip", "stop"], domain=review.domain,
                           reason=review.reason)
            return False
        if review is not None and review.policy == "ask":
            if review.domain and not review.once:  # a page on a domain that is neither allowed nor blocked
                decision, _ = await self.ask("domain", review.code or "open",
                                             ["allow_once", "allow_domain", "skip", "stop"], domain=review.domain,
                                             reason=review.reason)
                if decision == "allow_domain":
                    self.backend.allow_domain(review.domain)
            else:
                decision, _ = await self.ask("submit", review.code or "submit", ["allow_once", "skip", "stop"],
                                             reason=review.reason)
            return decision != "skip"
        if step.get("submits"):  # the recording saw it submit, or could not tell it did not
            decision, _ = await self.ask("submit", "recorded", ["allow_once", "skip", "stop"])
            return decision != "skip"
        return True
