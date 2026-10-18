"""Provider-neutral message, tool and streaming types shared by every SPIKE component."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None  # tool name for role="tool"
    # parts of `content` that are the user's file contents; a provider not allowed to see files gets a notice instead
    private: list[str] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (object)


@dataclass
class Capabilities:
    """What a backend can do natively. SPIKE emulates what it can and reports the rest."""

    streaming: bool = True
    native_tools: bool = False
    json_schema: bool = False  # constrained structured output
    adapters: bool = False  # per-request LoRA selection (llama.cpp)
    reasoning: bool = False  # exposes separate reasoning stream
    vision: bool = False
    max_context: int | None = None


@dataclass
class ChatRequest:
    messages: list[Message]
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    stop: list[str] = field(default_factory=list)
    adapter: str | None = None  # specialist adapter name, resolved by providers that support it
    json_schema: dict[str, Any] | None = None
    reasoning: bool | None = None  # request thinking mode when the model supports it


EventKind = Literal["text", "reasoning", "tool_call", "usage", "notice", "done", "error"]


@dataclass
class StreamEvent:
    kind: EventKind
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    notice: dict[str, Any] | None = None  # kind="notice": something SPIKE did to the request, for the UI


class ProviderError(RuntimeError):
    """Raised for transport, auth or protocol failures; message is safe to show to users."""


class PaidCallBlocked(ProviderError):
    """Raised when a paid provider is used without the user's explicit authorization."""


class SpendLimitReached(ProviderError):
    """Raised when a provider has used up the monthly limit the user set for it."""
