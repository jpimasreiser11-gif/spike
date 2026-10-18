"""OpenAI Chat Completions compatible backends.

Covers llama.cpp's llama-server, Ollama, LM Studio, vLLM and hosted APIs (OpenAI, DeepSeek, OpenRouter,
Groq, Mistral, Together, Gemini's OpenAI endpoint). Differences between them are expressed as
capabilities rather than subclasses wherever possible.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from spike.core.types import (
    Capabilities,
    ChatRequest,
    Message,
    PaidCallBlocked,
    ProviderError,
    StreamEvent,
    ToolCall,
)
from spike.providers.base import Provider, iter_sse, raise_for_status
from spike.providers.tool_emulation import (
    StreamingToolFilter,
    flatten_tool_messages,
    parse_tool_calls,
    tools_system_prompt,
)


def _to_openai_message(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
            }
            for c in m.tool_calls
        ]
        if not m.content:
            out["content"] = None
    return out


class OpenAICompatProvider(Provider):
    def default_capabilities(self) -> Capabilities:
        return Capabilities(streaming=True, native_tools=True, json_schema=True)

    # Hooks for subclasses -------------------------------------------------
    def extra_body(self, request: ChatRequest) -> dict[str, Any]:
        return {}

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.config.headers}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    # ----------------------------------------------------------------------
    def build_payload(self, request: ChatRequest) -> tuple[dict[str, Any], bool]:
        caps = self.capabilities
        emulate_tools = bool(request.tools) and not caps.native_tools
        messages = list(request.messages)
        if emulate_tools:
            messages = flatten_tool_messages(messages)
            prompt = tools_system_prompt(request.tools)
            if messages and messages[0].role == "system":
                messages[0] = Message(role="system", content=messages[0].content + "\n\n" + prompt)
            else:
                messages.insert(0, Message(role="system", content=prompt))

        payload: dict[str, Any] = {
            "model": request.model or self.config.model,
            "messages": [_to_openai_message(m) for m in messages],
            "stream": True,
        }
        if self.config.capabilities.get("stream_usage", True):
            payload["stream_options"] = {"include_usage": True}
        for key in ("temperature", "top_p", "max_tokens"):
            value = getattr(request, key)
            if value is not None:
                payload[key] = value
        if request.stop:
            payload["stop"] = request.stop
        if request.tools and not emulate_tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in request.tools
            ]
        if request.json_schema is not None and caps.json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "spike_output", "schema": request.json_schema, "strict": True},
            }
        payload.update(self.extra_body(request))
        return payload, emulate_tools

    def check_authorized(self) -> None:
        if self.config.paid and not self.config.allow_paid:
            raise PaidCallBlocked(
                f"{self.config.name} may bill your account. Enable 'Allow paid requests' for this provider in "
                "Settings → Providers to use it."
            )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        try:
            self.check_authorized()
        except PaidCallBlocked as exc:
            yield StreamEvent(kind="error", text=str(exc))
            return
        payload, emulate_tools = self.build_payload(request)
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        tool_filter = StreamingToolFilter() if emulate_tools else None
        pending: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        try:
            async with self.client.stream("POST", url, headers=self.headers(), json=payload) as response:
                await raise_for_status(response, self.config.name)
                async for _event, data in iter_sse(response):
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if "error" in chunk:
                        err = chunk["error"]
                        yield StreamEvent(kind="error", text=str(err.get("message", err) if isinstance(err, dict) else err))
                        return
                    if chunk.get("usage"):
                        yield StreamEvent(kind="usage", usage=self._usage(chunk))
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        if reasoning:
                            yield StreamEvent(kind="reasoning", text=reasoning)
                        content = delta.get("content")
                        if content:
                            visible = tool_filter.feed(content) if tool_filter else content
                            if visible:
                                yield StreamEvent(kind="text", text=visible)
                        for tc in delta.get("tool_calls") or []:
                            slot = pending.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except ProviderError as exc:
            yield StreamEvent(kind="error", text=str(exc))
            return
        except Exception as exc:  # network failures
            yield StreamEvent(kind="error", text=f"{self.config.name}: connection failed: {exc.__class__.__name__}: {exc}")
            return

        for index in sorted(pending):
            slot = pending[index]
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                yield StreamEvent(kind="text", text=f"\n[model produced an invalid tool call for '{slot['name']}']")
                continue
            yield StreamEvent(
                kind="tool_call",
                tool_call=ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=args),
            )
        if tool_filter is not None:
            tail = tool_filter.flush()
            if tail:
                yield StreamEvent(kind="text", text=tail)
            _visible, calls, malformed = parse_tool_calls(tool_filter.raw)
            for block in malformed:
                yield StreamEvent(kind="text", text="\n" + block)
            for call in calls:
                yield StreamEvent(kind="tool_call", tool_call=call)
            if calls:
                finish_reason = "tool_calls"
        yield StreamEvent(kind="done", finish_reason=finish_reason)

    @staticmethod
    def _usage(chunk: dict[str, Any]) -> dict[str, Any]:
        usage = dict(chunk.get("usage") or {})
        if chunk.get("timings"):  # llama.cpp performance counters
            usage["timings"] = chunk["timings"]
        return usage

    async def list_models(self) -> list[str]:
        url = self.config.base_url.rstrip("/") + "/models"
        response = await self.client.get(url, headers=self.headers())
        await raise_for_status(response, self.config.name)
        data = response.json()
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
