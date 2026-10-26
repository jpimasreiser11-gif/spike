"""One desktop task: the provider's computer-use loop with SPIKE's rules around it.

- Every action that changes anything waits for the user: a card with the screenshot region and the action, answered
  with approve, "approve the next N" (N from 2 to 5, only for actions that are not sensitive), deny or stop. Actions
  that buy, send, delete, close a program, press Enter or type into a password field always ask, batch or not.
- A task takes at most `max_steps` steps (an action or a screenshot the model asked for), and stops at once when the
  user presses Stop, turns the setting off, or closes the page; a waiting card nobody answers ends the task.
- Screenshots go to the one provider the user chose for this task, through the provider guard (paid requests, spending
  limits, the privacy setting). They stay in memory; only the ones the user asked to keep are written, for the proof.
The loop yields events like the chat does; the log it keeps has the actions and what the user decided, never images."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.core.context import estimate_tokens
from spike.core.types import ProviderError
from spike.desktop.actions import (
    CLICKS,
    Action,
    ActionError,
    classify,
    describe,
    parse_action,
    region_for,
    summary,
)
from spike.desktop.adapters import NOT_EXECUTED, SYSTEM, AnthropicAdapter, Call, image_tokens
from spike.desktop.driver import Driver, DriverError, Shot, parse_modifiers
from spike.desktop.settings import HARD_MAX_STEPS
from spike.providers.guard import call_cost

MAX_BATCH = 5  # "approve the next N actions": never more than this
APPROVAL_TIMEOUT_S = 300.0
STALE_S = 30.0  # a started task whose events nobody reads is not holding the place after this long
SETTLE_S = 0.8  # the screen needs a moment to show what an action did
KEEP_SHOTS = 12  # screenshots kept in memory for the cards
OUT_TOKENS = 300  # a model reply, for the estimate
TURN_TEXT_TOKENS = 250  # its words and the result text, for the estimate


class Refused(Exception):
    """The task may not start. `code` names why so the app can say it in the user's language."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Stopped(Exception):
    """The user pressed Stop (or the task was closed) while something was running."""


@dataclass(frozen=True)
class Decision:
    """The user's answer to a card. kind: approve | batch | deny | stop | timeout; `n` for batch (2 to MAX_BATCH)."""

    kind: str
    n: int = 1


@dataclass
class Pending:
    id: str
    task_id: str
    future: asyncio.Future[Decision]


class DesktopBroker:
    """The cards waiting for an answer. Like the tool permission broker, the answer comes through the app's API; unlike
    it, nothing is remembered: "always allow" does not exist for the desktop."""

    def __init__(self, timeout_s: float = APPROVAL_TIMEOUT_S):
        self.timeout_s = timeout_s
        self.pending: dict[str, Pending] = {}

    def open(self, task_id: str, action_id: str) -> Pending:
        pending = Pending(action_id, task_id, asyncio.get_running_loop().create_future())
        self.pending[action_id] = pending
        return pending

    async def wait(self, pending: Pending) -> Decision:
        try:
            return await asyncio.wait_for(asyncio.shield(pending.future), timeout=self.timeout_s)
        except TimeoutError:
            return Decision("timeout")
        finally:
            self.pending.pop(pending.id, None)

    def resolve(self, action_id: str, decision: str, n: int = 1) -> Decision | None:
        """Answer a card; the decision as it counts (a batch is capped at MAX_BATCH), or None if no card waits."""
        if decision not in ("approve", "approve_batch", "deny", "stop"):
            raise ValueError(f"invalid decision '{decision}'")
        pending = self.pending.get(action_id)
        if pending is None or pending.future.done():
            return None
        if decision == "approve_batch":
            n = min(int(n), MAX_BATCH)
            answer = Decision("batch", n) if n >= 2 else Decision("approve")
        else:
            answer = Decision({"approve_batch": "batch"}.get(decision, decision))
        pending.future.set_result(answer)
        return answer

    def cancel(self, task_id: str) -> None:
        """Answer every card of a task that is ending with a stop, and forget them."""
        for key, pending in list(self.pending.items()):
            if pending.task_id == task_id:
                self.pending.pop(key, None)
                if not pending.future.done():
                    pending.future.set_result(Decision("stop"))


@dataclass
class Outcome:
    """What one call came to: the tool_result for the model, whether the rest of the batch is skipped, and how the
    task ends if it does."""

    block: dict[str, Any] | None
    halt: bool = False
    end: str | None = None


def estimate(max_steps: int, shot_size: tuple[int, int], overhead: int, limits: dict[str, Any]) -> dict[str, Any]:
    """An upper bound of what a task of `max_steps` steps sends and costs: every request carries the tool definition and
    all the screenshots so far (the history is never cut), and no caching is assumed. The real numbers are the ones the
    provider reports; they appear in the call log."""
    img = image_tokens(*shot_size)
    calls = max_steps + 1
    system = estimate_tokens(SYSTEM)
    tokens_in = sum(overhead + system + k * (img + TURN_TEXT_TOKENS) for k in range(1, calls + 1))
    tokens_out = calls * OUT_TOKENS
    return {"max_steps": max_steps, "calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "screenshot_tokens": img, "overhead_tokens": overhead, "cost": call_cost(limits, tokens_in, tokens_out)}


class DesktopTask:
    """One task. `run()` yields the events; `stop()` ends it from outside; `record()` is what is kept of it."""

    def __init__(self, goal: str, provider: Any, driver: Driver, adapter_cls: type[AnthropicAdapter],
                 settings: dict[str, Any], broker: DesktopBroker, *, enabled: Callable[[], bool] = lambda: True,
                 shot_dir: Path | None = None, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 settle_s: float = SETTLE_S, estimate_for: dict[str, Any] | None = None):
        self.id = f"dsk_{uuid.uuid4().hex[:10]}"
        self.goal, self.provider, self.driver, self.adapter_cls = goal, provider, driver, adapter_cls
        self.settings, self.broker, self.enabled = settings, broker, enabled
        self.shot_dir, self.sleep, self.settle_s = shot_dir, sleep, settle_s
        self.max_steps = min(int(settings["max_steps"]), HARD_MAX_STEPS)  # whatever the setting holds
        self.estimate_for = estimate_for
        self.stopping = asyncio.Event()
        self.shots: dict[int, bytes] = {}
        self.shot_count = 0
        self.last: Shot | None = None
        self.batch_left = 0
        self.steps = 0
        self.actions: list[dict[str, Any]] = []
        self.texts: list[str] = []
        self.usage = {"input": 0, "output": 0, "calls": 0}
        self.reason = ""
        self.final = ""
        self.error: str | None = None
        self.started = time.time()
        self.running = False  # from start() until run() ends
        self.iterating = False  # run() has begun
        self.adapter: AnthropicAdapter | None = None
        self.kept: list[str] = []

    # ------------------------------------------------------------------ control
    def stop(self) -> None:
        self.stopping.set()
        self.broker.cancel(self.id)

    def stopped(self) -> bool:
        return self.stopping.is_set()

    async def until_stopped(self, work: Awaitable[Any]) -> Any:
        """Wait for `work`, or raise Stopped as soon as the user stops the task (the work is cancelled)."""
        job, halt = asyncio.ensure_future(work), asyncio.ensure_future(self.stopping.wait())
        try:
            await asyncio.wait({job, halt}, return_when=asyncio.FIRST_COMPLETED)
            if job.done():
                return job.result()
            raise Stopped
        finally:
            for fut in (job, halt):
                if not fut.done():
                    fut.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await fut

    async def shoot(self) -> Shot:
        """A fresh screenshot, kept for the cards (the last KEEP_SHOTS) and, if the user asked, on disk."""
        shot = await asyncio.to_thread(self.driver.screenshot)
        self.shot_count += 1
        self.last, self.shots[self.shot_count] = shot, shot.png
        for old in [n for n in self.shots if n <= self.shot_count - KEEP_SHOTS]:
            del self.shots[old]
        if self.shot_dir is not None:
            self.shot_dir.mkdir(parents=True, exist_ok=True)
            name = f"shot-{self.shot_count:03d}.png"
            (self.shot_dir / name).write_bytes(shot.png)
            self.kept.append(name)
        return shot

    # ------------------------------------------------------------------ the loop
    def busy(self) -> bool:
        """Whether this task still holds the one place for tasks (one that was started but whose stream never began
        lets go after a while)."""
        return self.running and (self.iterating or time.time() - self.started < STALE_S)

    async def run(self) -> AsyncIterator[dict[str, Any]]:
        self.running = self.iterating = True
        try:
            async for ev in self._run():
                yield ev
        finally:
            self.running = False
            self.broker.cancel(self.id)
            close = getattr(self.driver, "close", None)
            if callable(close):
                close()

    def _problem(self) -> str | None:
        """Why the task cannot go on, if the setting or the provider changed since it started."""
        if not self.enabled():
            return "Desktop actions were turned off in Settings."
        if self.provider.config.local:
            return "A local model never does desktop actions."
        return None

    async def _run(self) -> AsyncIterator[dict[str, Any]]:
        cfg = self.provider.config
        try:
            shot = await self.until_stopped(self.shoot())
        except Stopped:
            self.reason = "stopped"
            yield self._done()
            return
        except DriverError as exc:
            yield self._fail(f"The screen could not be captured: {exc}")
            return
        self.adapter = adapter = self.adapter_cls(cfg.model, (shot.width, shot.height), self.driver.supports,
                                                  self.settings["tool"])
        yield {"type": "desktop_start", "task": self.id, "goal": self.goal, "provider": cfg.name, "model": cfg.model,
               "max_steps": self.max_steps, "tool": adapter.variant, "estimate": self.estimate_for,
               "screen": {"width": shot.screen_width, "height": shot.screen_height, "shot_width": shot.width,
                          "shot_height": shot.height}, "shot": self.shot_count}
        messages = [adapter.first_message(self.goal, shot.png)]
        try:
            while True:
                if self.stopped():
                    self.reason = "stopped"
                elif self.steps >= self.max_steps:
                    self.reason = "step_limit"
                elif problem := self._problem():
                    self.error, self.reason = problem, "error"
                    yield {"type": "desktop_error", "message": problem}
                if self.reason:
                    break
                turn = adapter.parse(await self.until_stopped(
                    self.provider.send_raw(adapter.payload(messages), beta=adapter.betas)))
                self._count(turn.usage)
                if turn.text:
                    self.texts.append(turn.text[:2000])
                    yield {"type": "desktop_text", "text": turn.text[:2000]}
                messages.append(adapter.assistant_message(turn))
                if not turn.calls:
                    self.final = turn.text
                    self.reason = {"refusal": "refused", "max_tokens": "cut"}.get(turn.stop_reason, "finished")
                    break
                results: list[dict[str, Any]] = []
                halted = False
                for call in turn.calls:
                    if halted or self.stopped() or self.steps >= self.max_steps:
                        results.append(adapter.result(call, NOT_EXECUTED if halted else "Not executed: the task is "
                                                      "ending.", error=True))
                        continue
                    self.steps += 1
                    out: list[Outcome] = []
                    async for ev in self._handle(call, turn.text, out):
                        yield ev
                    outcome = out[0]
                    if outcome.block is not None:
                        results.append(outcome.block)
                    halted = halted or outcome.halt
                    if outcome.end:
                        self.reason = outcome.end
                        break
                if self.reason:
                    break
                messages.append(adapter.results_message(results))
        except Stopped:
            self.reason = "stopped"
        except (ProviderError, DriverError) as exc:
            self.error, self.reason = str(exc), "error"
            yield {"type": "desktop_error", "message": str(exc)}
        yield self._done()

    def _count(self, usage: dict[str, Any]) -> None:
        from spike.providers.guard import usage_tokens

        self.usage["calls"] += 1
        if counted := usage_tokens(usage or {}):
            self.usage["input"] += counted[0]
            self.usage["output"] += counted[1]

    def _fail(self, message: str) -> dict[str, Any]:
        self.error, self.reason = message, "error"
        return self._done()

    def _done(self) -> dict[str, Any]:
        limits = self.provider.limits() if hasattr(self.provider, "limits") else {}
        return {"type": "desktop_done", "task": self.id, "reason": self.reason or "finished", "steps": self.steps,
                "text": self.final, "error": self.error, "usage": dict(self.usage),
                "cost": call_cost(limits, self.usage["input"], self.usage["output"]),
                "shots": list(self.kept)}

    # ------------------------------------------------------------------ one call
    async def _handle(self, call: Call, commentary: str, out: list[Outcome]) -> AsyncIterator[dict[str, Any]]:
        adapter = self.adapter
        assert adapter is not None
        try:
            action = parse_action(call.name, call.input)
        except ActionError as exc:
            self._log(call.name, {"name": call.name}, str(exc), decision="refused", ok=False)
            out.append(Outcome(adapter.result(call, str(exc), error=True), halt=True))
            return
        if action.name not in self.driver.supports and action.name != "wait":
            message = f"'{action.name}' is not available on this computer: use the other actions"
            self._log(action.name, describe(action), message, decision="refused", ok=False)
            out.append(Outcome(adapter.result(call, message, error=True), halt=True))
            return
        step_id = f"{self.id}_{self.steps}"
        if action.passive:
            async for ev in self._passive(call, action, step_id, out):
                yield ev
            return
        secure = await self._secure_field() if action.name == "type" else None
        sensitive = classify(action, commentary, secure)
        masked = bool(sensitive and sensitive.kind == "password" and action.name == "type")
        auto = sensitive is None and self.batch_left > 0
        shot = self.last
        assert shot is not None
        card = {"type": "desktop_action", "id": step_id, "task": self.id, "step": self.steps, "action": describe(action, masked),
                "summary": summary(action, masked), "region": region_for(action, shot.width, shot.height),
                "shot": self.shot_count, "masked": masked, "auto": auto, "note": commentary[:400],
                "sensitive": {"kind": sensitive.kind, "reason": sensitive.reason} if sensitive else None}
        decision = Decision("approve")
        if auto:
            decision = Decision("auto")  # the user approved it ahead of time, in a batch
            self.batch_left -= 1
            yield card
            yield {"type": "desktop_resolved", "id": step_id, "decision": "auto", "left": self.batch_left}
        else:
            self.batch_left = 0  # a card that asks ends any batch: the user is looking again
            pending = self.broker.open(self.id, step_id)
            yield card
            decision = await self.until_stopped(self.broker.wait(pending))
            if decision.kind == "batch" and sensitive is not None:
                decision = Decision("approve")  # a sensitive action is approved for itself only
            if decision.kind == "batch":
                self.batch_left = decision.n - 1
            yield {"type": "desktop_resolved", "id": step_id, "decision": decision.kind, "n": decision.n,
                   "left": self.batch_left}
        shown = describe(action, masked)
        if decision.kind in ("stop", "timeout"):
            end = "stopped" if decision.kind == "stop" else "timeout"
            self._log(action.name, shown, "", decision=decision.kind, ok=False, sensitive=sensitive)
            out.append(Outcome(None, halt=True, end=end))
            return
        if decision.kind == "deny":
            message = "The user did not approve this action. Do not repeat it; try something else or ask the user."
            self._log(action.name, shown, "", decision="deny", ok=False, sensitive=sensitive)
            yield {"type": "desktop_result", "id": step_id, "ok": False, "message": "denied"}
            out.append(Outcome(adapter.result(call, message, error=True), halt=True))
            return
        try:
            await self.until_stopped(asyncio.to_thread(self._perform, action, shot))
            await self.until_stopped(self.sleep(self.settle_s))
            fresh = await self.until_stopped(self.shoot())
        except DriverError as exc:
            self._log(action.name, shown, str(exc), decision=decision.kind, ok=False, sensitive=sensitive)
            yield {"type": "desktop_result", "id": step_id, "ok": False, "message": str(exc)}
            out.append(Outcome(adapter.result(call, str(exc), error=True), halt=True))
            return
        self._log(action.name, shown, "ok", decision=decision.kind, ok=True, sensitive=sensitive)
        yield {"type": "desktop_result", "id": step_id, "ok": True, "shot": self.shot_count}
        out.append(Outcome(adapter.result(call, "OK", png=fresh.png)))

    async def _passive(self, call: Call, action: Action, step_id: str, out: list[Outcome]
                       ) -> AsyncIterator[dict[str, Any]]:
        """screenshot, cursor_position, wait: nothing changes, so no card; they still count as steps."""
        adapter = self.adapter
        assert adapter is not None
        try:
            if action.name == "screenshot":
                shot = await self.until_stopped(self.shoot())
                block, extra = adapter.result(call, png=shot.png), {"shot": self.shot_count}
            elif action.name == "wait":
                await self.until_stopped(self.sleep(action.duration))
                block, extra = adapter.result(call, "OK"), {}
            else:
                x, y = await asyncio.to_thread(self.driver.cursor_position)
                shot = self.last
                if shot is not None:
                    x, y = round(x * shot.width / shot.screen_width), round(y * shot.height / shot.screen_height)
                block, extra = adapter.result(call, f"X={x},Y={y}"), {}
        except DriverError as exc:
            self._log(action.name, describe(action), str(exc), decision="auto", ok=False)
            yield {"type": "desktop_step", "id": step_id, "step": self.steps, "action": describe(action), "ok": False,
                   "message": str(exc)}
            out.append(Outcome(adapter.result(call, str(exc), error=True), halt=True))
            return
        self._log(action.name, describe(action), "ok", decision="auto", ok=True)
        yield {"type": "desktop_step", "id": step_id, "step": self.steps, "action": describe(action), "ok": True, **extra}
        out.append(Outcome(block))

    async def _secure_field(self) -> bool | None:
        try:
            return await asyncio.to_thread(self.driver.secure_field_focused)
        except Exception:  # not being able to tell is not a reason to stop
            return None

    def _perform(self, action: Action, shot: Shot) -> None:
        """Do `action` on the screen. The model's points are in its screenshot; the driver's are screen points."""
        d, name = self.driver, action.name

        def screen(point: tuple[int, int]) -> tuple[int, int]:
            return shot.to_screen(*point)

        mods = parse_modifiers(action.text) if name in CLICKS or name in ("scroll", "left_click_drag") else ()
        if name in CLICKS:
            x, y = screen(action.coordinate) if action.coordinate else d.cursor_position()
            button, count = CLICKS[name]
            d.click(x, y, button, count, mods)
        elif name == "mouse_move" and action.coordinate:
            d.move(*screen(action.coordinate))
        elif name == "left_click_drag" and action.start and action.coordinate:
            d.drag(*screen(action.start), *screen(action.coordinate), mods)
        elif name == "scroll":
            point = screen(action.coordinate) if action.coordinate else (None, None)
            d.scroll(point[0], point[1], action.direction, action.amount, mods)
        elif name == "type":
            d.type_text(action.text or "")
        elif name == "key":
            d.key(action.text or "", action.repeat)

    # ------------------------------------------------------------------ the record
    def _log(self, name: str, shown: dict[str, Any], result: str, *, decision: str, ok: bool,
             sensitive: Any = None) -> None:
        self.actions.append({"step": self.steps, "action": name, **{k: v for k, v in shown.items() if k != "name"},
                             "decision": decision, "ok": ok, **({"result": result} if result and result != "ok" else {}),
                             **({"sensitive": sensitive.kind} if sensitive else {}), "at": round(time.time(), 1)})

    def record(self) -> dict[str, Any]:
        """What is kept of the task in the chat and the proof package: the goal, every action with what the user decided
        and whether it worked, the totals. Screenshots are never in it; `shots` lists the files the user asked to keep."""
        cfg = self.provider.config
        return {"task": self.id, "goal": self.goal, "provider": cfg.name, "model": cfg.model,
                "tool": self.adapter.variant if self.adapter else None, "max_steps": self.max_steps,
                "steps": self.steps, "reason": self.reason or ("running" if self.running else "stopped"),
                "error": self.error, "final": self.final[:4000], "usage": dict(self.usage),
                "started": round(self.started, 1), "actions": self.actions[:200], "notes": self.texts[:50],
                "screenshots": "kept" if self.kept else "not kept", "shots": list(self.kept),
                "screen": ({"width": self.last.screen_width, "height": self.last.screen_height}
                           if self.last else None)}
