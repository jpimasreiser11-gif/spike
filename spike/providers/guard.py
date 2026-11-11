"""The layer between SPIKE and every provider it calls: it keeps the user's files away from providers that are not
allowed to see them, stops calls past the monthly limit the user set, and writes each call to the call log."""

from __future__ import annotations

import datetime as dt
import itertools
import threading
import time
import weakref
from collections.abc import AsyncIterator, Callable, Sequence
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, Protocol

from spike.core.context import CHARS_PER_TOKEN, estimate_tokens
from spike.core.types import (
    Capabilities,
    ChatRequest,
    Message,
    PaidCallBlocked,
    ProviderError,
    SpendLimitReached,
    StreamEvent,
)
from spike.providers.base import Provider, ProviderConfig
from spike.runtime.urls import strip_url_secrets

LIMIT_KEYS = ("monthly_tokens", "monthly_cost", "price_in", "price_out")
ANSWER_TOKENS = 1024  # what a running call without max_tokens is expected to answer, until this month's calls say more

# Calls still running, per call log and provider id, with the tokens (in, out) each is expected to use until it reports
# (O4-2). Monthly limits count them, so calls that start together stop where calls one after another would. Shared by
# every GuardedProvider of a provider (the server builds a new one when its settings change) and every thread.
_RUNNING: weakref.WeakKeyDictionary[Any, dict[str, dict[int, list[int]]]] = weakref.WeakKeyDictionary()
_RUNNING_LOCK = threading.RLock()
_KEYS = itertools.count()


CURRENT_CHAT: ContextVar[str | None] = ContextVar("spike_chat", default=None)  # set by the chat route

class CallLog(Protocol):
    def log_call(self, **row: Any) -> None: ...
    def usage_since(self, provider_id: str, since: float) -> dict[str, float]: ...


def withheld_notice(provider_name: str) -> str:
    return (f"[file content withheld: {provider_name} is not allowed to receive the user's files. If it is needed, "
            "tell the user they can allow it for this provider in Settings › Providers.]")


def redact(messages: list[Message], notice: str) -> tuple[list[Message], int]:
    """Messages with every private part replaced by `notice`, and how many parts were withheld. A part that is not
    found word for word withholds its whole message, so nothing private gets through by accident."""
    out, withheld = [], 0
    for m in messages:
        if not m.private:
            out.append(m)
            continue
        content = m.content
        for part in m.private:
            if part and part in content:
                content = content.replace(part, notice)
            elif part:
                content = notice
                break
        withheld += len([p for p in m.private if p])
        out.append(replace(m, content=content, private=[]))
    return out, withheld


def month_start(now: float | None = None) -> float:
    today = dt.datetime.fromtimestamp(now if now is not None else time.time())
    return today.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def call_cost(limits: dict[str, Any], tokens_in: int, tokens_out: int) -> float | None:
    """Cost at the prices the user entered (per million tokens); None when no price is set."""
    price_in, price_out = limits.get("price_in"), limits.get("price_out")
    if price_in is None and price_out is None:
        return None
    return tokens_in * float(price_in or 0) / 1e6 + tokens_out * float(price_out or 0) / 1e6


def usage_tokens(usage: dict[str, Any]) -> tuple[int, int] | None:
    """(input, output) tokens from an OpenAI- or Anthropic-style usage object."""
    tokens_in = usage.get("prompt_tokens", usage.get("input_tokens"))
    tokens_out = usage.get("completion_tokens", usage.get("output_tokens"))
    if tokens_in is None and tokens_out is None:
        return None
    tokens_in = int(tokens_in or 0) + int(usage.get("cache_creation_input_tokens") or 0) + \
        int(usage.get("cache_read_input_tokens") or 0)
    return tokens_in, int(tokens_out or 0)


def estimate_request(messages: Sequence[Message], tools: Sequence[Any]) -> int:
    """Estimated input tokens of a request: its messages and tool definitions."""
    return sum(estimate_tokens(m.content) for m in messages) + \
        sum(estimate_tokens(str(t.parameters)) + estimate_tokens(t.description) for t in tools)


class GuardedProvider(Provider):
    def __init__(self, inner: Provider, log: CallLog, limits: Callable[[], dict[str, Any]] = dict):
        self.inner = inner  # no Provider.__init__: the config and the HTTP client are the inner provider's
        self._client = None
        self.log = log
        self.limits = limits

    @property
    def config(self) -> ProviderConfig:  # type: ignore[override]
        return self.inner.config

    @config.setter
    def config(self, value: ProviderConfig) -> None:
        self.inner.config = value

    @property
    def computer_use_adapter(self) -> str | None:  # type: ignore[override]
        return self.inner.computer_use_adapter

    @property
    def capabilities(self) -> Capabilities:
        return self.inner.capabilities

    def default_capabilities(self) -> Capabilities:
        return self.inner.default_capabilities()

    async def list_models(self) -> list[str]:
        return await self.inner.list_models()

    async def aclose(self) -> None:
        await self.inner.aclose()

    def __getattr__(self, name: str) -> Any:  # provider-specific extras, e.g. llama.cpp's adapters()
        if name == "inner":
            raise AttributeError(name)
        return getattr(self.inner, name)

    @property
    def receives_files(self) -> bool:
        return self.config.local or self.config.share_files

    def _running(self) -> dict[int, list[int]]:
        with _RUNNING_LOCK:
            return _RUNNING.setdefault(self.log, {}).setdefault(self.config.id, {})

    def _usage(self, limits: dict[str, Any]) -> tuple[int, float, int]:
        """This month's tokens and cost so far, the calls still running counted with what they are expected to use,
        and how many of those tokens are the running calls'."""
        used = self.log.usage_since(self.config.id, month_start())
        with _RUNNING_LOCK:
            run_in = sum(slot[0] for slot in self._running().values())
            run_out = sum(slot[1] for slot in self._running().values())
        return (int(used["tokens_in"] + used["tokens_out"]) + run_in + run_out,
                float(used["cost"]) + (call_cost(limits, run_in, run_out) or 0.0), run_in + run_out)

    def blocked(self) -> str | None:
        """Why a call may not start now: paid requests not allowed, or a monthly limit reached by the calls logged
        this month and the calls still running (counted with what they are expected to use)."""
        cfg = self.config
        if cfg.paid and not cfg.allow_paid:
            return str(PaidCallBlocked(f"{cfg.name} may bill your account. Enable 'Allow paid requests' for this "
                                       "provider in Settings → Providers to use it."))
        if cfg.local:
            return None
        limits = self.limits()
        token_cap, cost_cap = limits.get("monthly_tokens"), limits.get("monthly_cost")
        if not token_cap and cost_cap is None:
            return None
        tokens, cost, running = self._usage(limits)
        still = f", {running:,} of them for calls still running" if running else ""
        if token_cap and tokens >= int(token_cap):
            return str(SpendLimitReached(f"{cfg.name}: the monthly limit is reached ({tokens:,} of {int(token_cap):,} "
                                         f"tokens this month{still}). Raise or remove it in Settings → Providers."))
        if cost_cap is not None and cost >= float(cost_cap):
            return str(SpendLimitReached(f"{cfg.name}: the monthly spending limit is reached ({cost:.2f} of "
                                         f"{float(cost_cap):.2f} this month, at the prices you entered"
                                         f"{', counting calls still running' if running else ''}). Raise or "
                                         "remove it in Settings → Providers."))
        return None

    def _start(self, request: ChatRequest | None) -> tuple[str | None, int | None]:
        """`blocked`, and when the call may start, its place among the calls still running, in one step, so two
        calls that start together cannot both read the limit before either is counted."""
        with _RUNNING_LOCK:
            if (reason := self.blocked()) is not None:
                return reason, None
            limits = self.limits()
            if self.config.local or (not limits.get("monthly_tokens") and limits.get("monthly_cost") is None):
                return None, None
            tokens_in = estimate_request(request.messages, request.tools) if request else 0
            answer = request.max_tokens if request and request.max_tokens else None
            if answer is None:
                used = self.log.usage_since(self.config.id, month_start())
                answer = max(ANSWER_TOKENS, int(used["tokens_out"] / used["calls"]) if used.get("calls") else 0)
            key = next(_KEYS)
            self._running()[key] = [tokens_in, int(answer), int(answer)]
            return None, key

    def _progress(self, key: int | None, out_chars: int) -> None:
        if key is not None and (slot := self._running().get(key)):
            slot[1] = max(slot[2], int(out_chars / CHARS_PER_TOKEN))

    def _finish(self, key: int | None) -> None:
        if key is not None:
            with _RUNNING_LOCK:
                self._running().pop(key, None)

    def blocked_for(self, calls: int, tokens_in: int, tokens_out: int) -> str | None:
        """`blocked`, asked before a batch of `calls` calls that will use `tokens_in` + `tokens_out` tokens in all:
        besides the paid-call permission and a limit already reached, a monthly limit the batch would cross. Nothing
        is logged. The check before each call (`stream`) still applies to every call of the batch."""
        if (reason := self.blocked()) is not None:
            return reason
        cfg = self.config
        if cfg.local or calls < 1:
            return None
        limits = self.limits()
        token_cap, cost_cap = limits.get("monthly_tokens"), limits.get("monthly_cost")
        if not token_cap and cost_cap is None:
            return None
        tokens, used_cost, running = self._usage(limits)
        still = f", counting {running:,} for calls still running" if running else ""
        if token_cap and tokens + tokens_in + tokens_out > int(token_cap):
            return str(SpendLimitReached(
                f"{cfg.name}: {calls} calls of up to {(tokens_in + tokens_out) // calls:,} tokens would cross the "
                f"monthly limit ({tokens:,} of {int(token_cap):,} tokens used this month{still}). Use fewer calls, or "
                "raise or remove the limit in Settings → Providers."))
        cost = call_cost(limits, tokens_in, tokens_out)
        if cost_cap is not None and cost is not None and used_cost + cost > float(cost_cap):
            return str(SpendLimitReached(
                f"{cfg.name}: {calls} calls (up to {cost:.2f} at the prices you entered) would cross the monthly "
                f"spending limit ({used_cost:.2f} of {float(cost_cap):.2f} used this month"
                f"{', counting calls still running' if running else ''}). Use fewer calls, or raise or remove the "
                "limit in Settings → Providers."))
        return None

    def screens_blocked(self) -> str | None:
        """Why this provider may not be sent screenshots of the user's screen now: the checks of every call (paid
        requests allowed, monthly limits) and the privacy setting. Screenshots are the user's private content: a remote
        provider gets them only where it may also receive the user's files."""
        if (reason := self.blocked()) is not None:
            return reason
        if not self.receives_files:
            return (f"{self.config.name} is not allowed to receive your files, so SPIKE will not send it screenshots "
                    "of your screen. Allow it in Settings → Providers (Send your files' contents to this provider) "
                    "to use it for desktop actions.")
        return None

    async def send_raw(self, payload: dict[str, Any], *, beta: Sequence[str] = ()) -> dict[str, Any]:
        """A desktop step: the guard's checks first (spending, paid requests, screenshots allowed), then the request,
        then the call log with the tokens the provider reports."""
        cfg = self.config
        row: dict[str, Any] = {"provider_id": cfg.id, "provider": cfg.name, "model": payload.get("model") or cfg.model,
                               "local": cfg.local, "conversation_id": CURRENT_CHAT.get()}
        with _RUNNING_LOCK:
            reason, key = self.screens_blocked(), None
            if reason is None:
                reason, key = self._start(None)
        if reason is not None:
            self.log.log_call(**row, status="blocked", detail=reason)
            raise ProviderError(reason)
        try:
            try:
                answer = await self.inner.send_raw(payload, beta=beta)
            except Exception as exc:
                self.log.log_call(**row, status="error", detail=strip_url_secrets(str(exc))[:500], tokens_in=0,
                                  tokens_out=0, estimated=False)
                raise
            usage = usage_tokens(answer.get("usage") or {}) if isinstance(answer, dict) else None
            self.log.log_call(**row, status="ok", detail="desktop step", tokens_in=(usage or (0, 0))[0],
                              tokens_out=(usage or (0, 0))[1], estimated=usage is None,
                              cost=None if cfg.local or usage is None else call_cost(self.limits(), *usage))
            return answer
        finally:
            self._finish(key)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        cfg = self.config
        row: dict[str, Any] = {"provider_id": cfg.id, "provider": cfg.name, "model": request.model or cfg.model,
                               "local": cfg.local, "conversation_id": CURRENT_CHAT.get()}
        reason, key = self._start(request)
        if reason is not None:
            self.log.log_call(**row, status="blocked", detail=reason)
            yield StreamEvent(kind="error", text=reason)
            return
        if any(m.images for m in request.messages) and not self.receives_files:
            self._finish(key)
            yield StreamEvent(kind="error", text="images_private")
            return
        call = self._stream(request, row, key)
        try:
            async for ev in call:
                yield ev
        finally:
            await call.aclose()  # a call stopped early is logged now, not when it is garbage-collected
            self._finish(key)    # after the log: a call always counts, as running or as logged

    async def _stream(self, request: ChatRequest, row: dict[str, Any], key: int | None) -> AsyncIterator[StreamEvent]:
        cfg = self.config
        messages, withheld = request.messages, 0
        if not self.receives_files:
            messages, withheld = redact(request.messages, withheld_notice(cfg.name))
        files_sent = 0 if withheld else sum(len([p for p in m.private if p]) + len(m.images) for m in messages)
        if withheld:
            yield StreamEvent(kind="notice", notice={"type": "privacy", "provider": cfg.name, "withheld": withheld})
        status, detail, usage, out_chars = "cancelled", "", None, 0
        try:
            async for ev in self.inner.stream(replace(request, messages=messages)):
                if ev.kind in ("text", "reasoning"):
                    out_chars += len(ev.text)
                    self._progress(key, out_chars)
                elif ev.kind == "tool_call" and ev.tool_call:
                    out_chars += len(ev.tool_call.name) + len(str(ev.tool_call.arguments))
                    self._progress(key, out_chars)
                elif ev.kind == "usage" and ev.usage:
                    usage = usage_tokens(ev.usage) or usage
                elif ev.kind == "error":
                    ev = replace(ev, text=strip_url_secrets(ev.text))  # an address in an error loses its key
                    status, detail = "error", ev.text[:500]
                elif ev.kind == "done" and status == "cancelled":
                    status = "ok"
                yield ev
            if status == "cancelled":
                status = "ok"
        finally:
            estimated = usage is None
            if usage is None and status == "error":
                usage = (0, 0)  # nothing came back: count it as not billed
            elif usage is None:
                usage = (estimate_request(messages, request.tools), int(out_chars / CHARS_PER_TOKEN) + (1 if out_chars else 0))
            self.log.log_call(**row, status=status, detail=detail, tokens_in=usage[0], tokens_out=usage[1],
                              estimated=estimated, cost=None if cfg.local else call_cost(self.limits(), *usage),
                              files_sent=files_sent, files_withheld=withheld)
