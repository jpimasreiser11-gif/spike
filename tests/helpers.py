"""Test doubles. The scripted provider replays fixed responses and records every request it receives."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from spike.core.types import Capabilities, ChatRequest, StreamEvent, ToolCall
from spike.providers.base import Provider, ProviderConfig

Script = Callable[[ChatRequest], list[StreamEvent]]


def text(*chunks: str) -> list[StreamEvent]:
    return [StreamEvent(kind="text", text=c) for c in chunks] + [StreamEvent(kind="done", finish_reason="stop")]


def call(name: str, args: dict, call_id: str = "c1") -> list[StreamEvent]:
    return [StreamEvent(kind="tool_call", tool_call=ToolCall(id=call_id, name=name, arguments=args)),
            StreamEvent(kind="done", finish_reason="tool_calls")]


class ScriptedProvider(Provider):
    def __init__(self, script: Script | list[list[StreamEvent]], name: str = "scripted", adapters: bool = True):
        super().__init__(ProviderConfig(id=name, kind="scripted", name=name, base_url="", model="test-model"))
        self.requests: list[ChatRequest] = []
        self._script = script
        self._adapters = adapters

    def default_capabilities(self) -> Capabilities:
        return Capabilities(native_tools=True, adapters=self._adapters)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if callable(self._script):
            events = self._script(request)
        else:
            events = self._script.pop(0) if self._script else text("(script exhausted)")
        for ev in events:
            yield ev

    async def list_models(self) -> list[str]:
        return ["test-model"]
