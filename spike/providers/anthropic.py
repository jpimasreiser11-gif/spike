"""Anthropic Messages API backend (native tools, streaming, extended thinking)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from spike.core.types import Capabilities, ChatRequest, Message, PaidCallBlocked, ProviderError, StreamEvent, ToolCall
from spike.providers.base import Provider, iter_sse, raise_for_status

API_VERSION = "2023-06-01"


def to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    def push(role: str, block: dict[str, Any]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].append(block)
        else:
            out.append({"role": role, "content": [block]})

    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            push("user", {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant":
            if m.content:
                push("assistant", {"type": "text", "text": m.content})
            for c in m.tool_calls:
                push("assistant", {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
        else:
            push("user", {"type": "text", "text": m.content})
    return "\n\n".join(p for p in system_parts if p), out


class AnthropicProvider(Provider):
    def default_capabilities(self) -> Capabilities:
        return Capabilities(streaming=True, native_tools=True, json_schema=False, reasoning=True, vision=True)

    def headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "x-api-key": self.config.api_key or "",
            "anthropic-version": API_VERSION,
            **self.config.headers,
        }

    def build_payload(self, request: ChatRequest) -> dict[str, Any]:
        system, messages = to_anthropic(request.messages)
        if request.json_schema is not None:
            system = (system + "\n\n" if system else "") + (
                "Respond with a single JSON object that validates against this JSON schema, and nothing else:\n"
                + json.dumps(request.json_schema)
            )
        payload: dict[str, Any] = {
            "model": request.model or self.config.model,
            "max_tokens": request.max_tokens or 4096,
            "messages": messages,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.stop:
            payload["stop_sequences"] = request.stop
        if request.tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in request.tools
            ]
        return payload

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if self.config.paid and not self.config.allow_paid:
            yield StreamEvent(kind="error", text=str(PaidCallBlocked(
                f"{self.config.name} may bill your account. Enable 'Allow paid requests' for this provider in "
                "Settings → Providers to use it.")))
            return
        url = self.config.base_url.rstrip("/") + "/messages"
        blocks: dict[int, dict[str, Any]] = {}
        stop_reason: str | None = None
        try:
            async with self.client.stream("POST", url, headers=self.headers(), json=self.build_payload(request)) as resp:
                await raise_for_status(resp, self.config.name)
                async for event, data in iter_sse(resp):
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    kind = obj.get("type", event)
                    if kind == "error":
                        yield StreamEvent(kind="error", text=obj.get("error", {}).get("message", "unknown error"))
                        return
                    if kind == "message_start":
                        usage = obj.get("message", {}).get("usage")
                        if usage:
                            yield StreamEvent(kind="usage", usage=usage)
                    elif kind == "content_block_start":
                        block = obj.get("content_block", {})
                        blocks[obj["index"]] = {**block, "partial": ""}
                    elif kind == "content_block_delta":
                        delta = obj.get("delta", {})
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            yield StreamEvent(kind="text", text=delta.get("text", ""))
                        elif dtype == "thinking_delta":
                            yield StreamEvent(kind="reasoning", text=delta.get("thinking", ""))
                        elif dtype == "input_json_delta":
                            blocks[obj["index"]]["partial"] += delta.get("partial_json", "")
                    elif kind == "content_block_stop":
                        block = blocks.get(obj["index"], {})
                        if block.get("type") == "tool_use":
                            try:
                                args = json.loads(block["partial"] or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            yield StreamEvent(
                                kind="tool_call", tool_call=ToolCall(id=block["id"], name=block["name"], arguments=args)
                            )
                    elif kind == "message_delta":
                        stop_reason = obj.get("delta", {}).get("stop_reason") or stop_reason
                        if obj.get("usage"):
                            yield StreamEvent(kind="usage", usage=obj["usage"])
        except ProviderError as exc:
            yield StreamEvent(kind="error", text=str(exc))
            return
        except Exception as exc:
            yield StreamEvent(kind="error", text=f"{self.config.name}: connection failed: {exc.__class__.__name__}: {exc}")
            return
        yield StreamEvent(kind="done", finish_reason="tool_calls" if stop_reason == "tool_use" else stop_reason)

    async def list_models(self) -> list[str]:
        response = await self.client.get(self.config.base_url.rstrip("/") + "/models", headers=self.headers())
        await raise_for_status(response, self.config.name)
        return sorted(m["id"] for m in response.json().get("data", []))
