"""The layer between SPIKE and every provider it calls: it keeps the user's files away from providers that are not
allowed to see them, stops calls past the monthly limit the user set, and writes each call to the call log."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any, Protocol

from spike.core.context import CHARS_PER_TOKEN, estimate_tokens
from spike.core.types import (
    Capabilities,
    ChatRequest,
    Message,
    PaidCallBlocked,
    SpendLimitReached,
    StreamEvent,
)
from spike.providers.base import Provider, ProviderConfig

LIMIT_KEYS = ("monthly_tokens", "monthly_cost", "price_in", "price_out")


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

    def blocked(self) -> str | None:
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
        used = self.log.usage_since(cfg.id, month_start())
        tokens = int(used["tokens_in"] + used["tokens_out"])
        if token_cap and tokens >= int(token_cap):
            return str(SpendLimitReached(f"{cfg.name}: the monthly limit is reached ({tokens:,} of {int(token_cap):,} "
                                         "tokens this month). Raise or remove it in Settings → Providers."))
        if cost_cap is not None and used["cost"] >= float(cost_cap):
            return str(SpendLimitReached(f"{cfg.name}: the monthly spending limit is reached ({used['cost']:.2f} of "
                                         f"{float(cost_cap):.2f} this month, at the prices you entered). Raise or "
                                         "remove it in Settings → Providers."))
        return None

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        cfg = self.config
        row: dict[str, Any] = {"provider_id": cfg.id, "provider": cfg.name, "model": request.model or cfg.model,
                               "local": cfg.local}
        if (reason := self.blocked()) is not None:
            self.log.log_call(**row, status="blocked", detail=reason)
            yield StreamEvent(kind="error", text=reason)
            return
        messages, withheld = request.messages, 0
        if not self.receives_files:
            messages, withheld = redact(request.messages, withheld_notice(cfg.name))
        files_sent = 0 if withheld else sum(len([p for p in m.private if p]) for m in messages)
        if withheld:
            yield StreamEvent(kind="notice", notice={"type": "privacy", "provider": cfg.name, "withheld": withheld})
        status, detail, usage, out_chars = "cancelled", "", None, 0
        try:
            async for ev in self.inner.stream(replace(request, messages=messages)):
                if ev.kind in ("text", "reasoning"):
                    out_chars += len(ev.text)
                elif ev.kind == "tool_call" and ev.tool_call:
                    out_chars += len(ev.tool_call.name) + len(str(ev.tool_call.arguments))
                elif ev.kind == "usage" and ev.usage:
                    usage = usage_tokens(ev.usage) or usage
                elif ev.kind == "error":
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
                tokens_in = sum(estimate_tokens(m.content) for m in messages) + \
                    sum(estimate_tokens(str(t.parameters)) + estimate_tokens(t.description) for t in request.tools)
                usage = (tokens_in, int(out_chars / CHARS_PER_TOKEN) + (1 if out_chars else 0))
            self.log.log_call(**row, status=status, detail=detail, tokens_in=usage[0], tokens_out=usage[1],
                              estimated=estimated, cost=None if cfg.local else call_cost(self.limits(), *usage),
                              files_sent=files_sent, files_withheld=withheld)
