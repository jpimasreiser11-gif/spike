"""Small, explicit Lab experiments. Probes bypass capability emulation, never the spending guard.

A successful tiny request is evidence for that request only. In particular the context probe measures a small lower
bound, not the provider's advertised context window. Results never update the user's capability settings.
"""

from __future__ import annotations

import base64
import json
import struct
import time
import zlib
from collections.abc import AsyncIterator
from typing import Any

import httpx

from spike.core.context import CHARS_PER_TOKEN, estimate_tokens
from spike.core.types import Capabilities, ChatRequest, Message, StreamEvent
from spike.providers.anthropic import AnthropicProvider
from spike.providers.base import Provider, iter_sse
from spike.providers.guard import GuardedProvider, call_cost, usage_tokens
from spike.providers.openai_compat import OpenAICompatProvider

PROBES = ("tools", "json", "vision", "streaming", "context")
MAX_OUTPUT = 128
CONTEXT_ANSWER = "LAB_START_7 LAB_END_9"
CONTEXT_PROMPT = "LAB_START_7 " + " ".join(["sample"] * 128) + (
    " LAB_END_9\nReturn the first and last marker, separated by one space.")


def red_image() -> str:
    """An original 8x8 red PNG, generated without an image dependency or an external asset."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 8, 8, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 8) * 8)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def probe_payload(model: str, capability: str, native: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "max_tokens": MAX_OUTPUT, "stream": False,
                                "messages": [{"role": "user", "content": "Reply exactly OK."}]}
    if capability == "tools":
        payload["messages"][0]["content"] = 'Call lab_echo with value "ok".'
        payload["tools"] = [{"type": "function", "function": {"name": "lab_echo", "description": "Echo a value",
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}}}]
        payload["tool_choice"] = {"type": "function", "function": {"name": "lab_echo"}}
    elif capability == "json":
        payload["messages"][0]["content"] = 'Reply with the JSON object {"ok":true}.'
        payload["response_format"] = {"type": "json_object"}
    elif capability == "vision":
        payload["messages"][0]["content"] = [{"type": "text", "text": "What color is this image? One English word."},
                                                {"type": "image_url", "image_url": {"url": red_image()}}]
    elif capability == "streaming":
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    elif capability == "context":
        payload["messages"][0]["content"] = CONTEXT_PROMPT
    if native:
        if "tools" in payload:
            function = payload["tools"][0]["function"]
            payload["tools"] = [{"name": function["name"], "description": function["description"],
                                 "input_schema": function["parameters"]}]
            payload["tool_choice"] = {"type": "tool", "name": "lab_echo"}
        if capability == "vision":
            payload["messages"][0]["content"][1] = {"type": "image", "source": {"type": "base64",
                "media_type": "image/png", "data": red_image().split(",", 1)[1]}}
        payload.pop("stream_options", None)
    return payload


def probe_capabilities(provider: Provider) -> tuple[str, ...]:
    """Native Messages has no JSON mode in SPIKE; never mistake prompted JSON for a native mode."""
    if isinstance(provider, AnthropicProvider):
        return tuple(c for c in PROBES if c != "json")
    return PROBES if isinstance(provider, OpenAICompatProvider) else ()


class ProbeProvider(Provider):
    """A single raw compatible request inside GuardedProvider, including logging and monthly accounting.

    A provider accepting a flag but returning plain text does not pass. Tools are parsed but never executed; images
    contain no user data. HTTP errors are recorded as generic failures so a server cannot echo credentials into runs.
    """

    def __init__(self, inner: OpenAICompatProvider | AnthropicProvider, capability: str):
        super().__init__(inner.config, inner.client)
        self.inner, self.capability = inner, capability

    def default_capabilities(self) -> Capabilities:
        return Capabilities()

    async def list_models(self) -> list[str]:
        return []

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        native = isinstance(self.inner, AnthropicProvider)
        payload = probe_payload(request.model or self.config.model, self.capability, native)
        endpoint = "/messages" if native else "/chat/completions"
        observed = False
        try:
            async with self.client.stream("POST", self.config.base_url.rstrip("/") + endpoint,
                                          headers=self.inner.headers(), json=payload, timeout=30) as response:
                if response.status_code >= 400:
                    yield StreamEvent(kind="error", text="probe_failed")
                    return
                if self.capability == "streaming":
                    usage: dict[str, Any] = {}
                    async for _, raw in iter_sse(response):
                        if raw.strip() == "[DONE]":
                            break
                        data = json.loads(raw)
                        if data.get("error") or data.get("type") == "error":
                            yield StreamEvent(kind="error", text="probe_failed")
                            return
                        if native:
                            usage.update(data.get("message", {}).get("usage") or {})
                            usage.update(data.get("usage") or {})
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                observed = True
                                yield StreamEvent(kind="reasoning", text=delta["text"])
                            continue
                        if data.get("usage"):
                            yield StreamEvent(kind="usage", usage=data["usage"])
                        for choice in data.get("choices", []):
                            if choice.get("delta", {}).get("content"):
                                yield StreamEvent(kind="reasoning", text=choice["delta"]["content"])
                        observed |= any(isinstance(c.get("delta", {}).get("content"), str)
                                        and bool(c["delta"]["content"]) for c in data.get("choices", []))
                    if native and usage:
                        yield StreamEvent(kind="usage", usage=usage)
                else:
                    data = json.loads(await response.aread())
                    if data.get("usage"):
                        yield StreamEvent(kind="usage", usage=data["usage"])
                    if native:
                        blocks = data["content"]
                        message = {"content": "".join(b.get("text", "") for b in blocks), "tool_calls": [
                            {"function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                            for b in blocks if b.get("type") == "tool_use"]}
                    else:
                        message = data["choices"][0]["message"]
                    content = message.get("content") or ""
                    yield StreamEvent(kind="reasoning", text=content + json.dumps(message.get("tool_calls", [])))
                    if self.capability == "tools":
                        observed = any(c["function"]["name"] == "lab_echo"
                                       and json.loads(c["function"]["arguments"]) == {"value": "ok"}
                                       for c in message.get("tool_calls", []))
                    elif self.capability == "json":
                        observed = json.loads(content) == {"ok": True}
                    elif self.capability == "vision":
                        observed = content.strip().lower().strip(".") == "red"
                    else:
                        observed = content.strip() == CONTEXT_ANSWER
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            yield StreamEvent(kind="error", text="probe_failed")
            return
        yield StreamEvent(kind="text", text="observed" if observed else "not_observed")
        yield StreamEvent(kind="done")


def probe_request(model: str, capability: str, native: bool = False) -> ChatRequest:
    """Count the actual synthetic payload for guard estimates (vision billing remains provider-dependent)."""
    payload = probe_payload(model, capability, native)
    return ChatRequest(messages=[Message(role="user", content=json.dumps(payload))], model=model, max_tokens=MAX_OUTPUT)


async def measure(provider: GuardedProvider, request: ChatRequest) -> dict[str, Any]:
    start = time.perf_counter()
    text, usage, error, extra_chars = "", None, False, 0
    try:
        async for event in provider.stream(request):
            if event.kind == "text":
                text += event.text
            elif event.kind == "reasoning":
                extra_chars += len(event.text)
            elif event.kind == "usage" and event.usage:
                usage = usage_tokens(event.usage) or usage
            elif event.kind == "error":
                error = True
    except Exception:
        error = True  # never persist provider exceptions or secrets echoed by a remote server
    estimated = usage is None
    tokens_in, tokens_out = usage or (sum(estimate_tokens(m.content) for m in request.messages), int((len(text) + extra_chars) / CHARS_PER_TOKEN) + 1)
    return {"output": text if not error else "", "status": "failed" if error else "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 3), "tokens_in": tokens_in,
            "tokens_out": tokens_out, "estimated_tokens": estimated,
            "cost": call_cost(provider.limits(), tokens_in, tokens_out)}
