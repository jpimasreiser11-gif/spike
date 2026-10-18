"""Provider interface. Every backend (local llama.cpp, Ollama, OpenAI-compatible APIs, Anthropic) implements it."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from spike.core.types import Capabilities, ChatRequest, ProviderError, StreamEvent


@dataclass
class ProviderConfig:
    id: str
    kind: str  # "openai" | "anthropic" | "llamacpp"
    name: str
    base_url: str
    model: str = ""
    api_key: str | None = None  # injected from the secret store at runtime, never persisted here
    paid: bool = False  # remote providers may bill the user
    allow_paid: bool = False  # explicit user authorization for paid calls
    local: bool = False
    share_files: bool = False  # a remote provider receives the user's file contents only when the user allows it
    headers: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)  # user overrides
    timeout_s: float = 600.0


class Provider(ABC):
    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout_s, connect=10.0))
        return self._client

    @property
    def capabilities(self) -> Capabilities:
        caps = self.default_capabilities()
        for key, value in self.config.capabilities.items():
            if hasattr(caps, key):
                setattr(caps, key, value)
        return caps

    @abstractmethod
    def default_capabilities(self) -> Capabilities: ...

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    async def complete(self, request: ChatRequest) -> tuple[str, list[StreamEvent]]:
        """Collect a full response. Returns (text, all events)."""
        events: list[StreamEvent] = []
        parts: list[str] = []
        async for event in self.stream(request):
            events.append(event)
            if event.kind == "text":
                parts.append(event.text)
            elif event.kind == "error":
                raise ProviderError(event.text)
        return "".join(parts), events

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def iter_sse(response: httpx.Response) -> AsyncIterator[tuple[str | None, str]]:
    """Yield (event, data) pairs from a Server-Sent Events response."""
    event: str | None = None
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event, data_lines = None, []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event = value
        elif name == "data":
            data_lines.append(value)
    if data_lines:
        yield event, "\n".join(data_lines)


async def raise_for_status(response: httpx.Response, provider_name: str) -> None:
    if response.status_code < 400:
        return
    body = (await response.aread()).decode("utf-8", "replace")[:500]
    detail = body
    try:
        parsed = json.loads(body)
        err = parsed.get("error", parsed)
        detail = err.get("message", body) if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        pass
    if response.status_code in (401, 403):
        raise ProviderError(f"{provider_name}: authentication failed ({response.status_code}). Check the API key.")
    raise ProviderError(f"{provider_name}: HTTP {response.status_code}: {detail}")
