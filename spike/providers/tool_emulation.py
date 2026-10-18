"""Prompt-level tool calling for models whose API has no native tool support.

The protocol is the Hermes/Qwen style `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`, which
Qwen-family models are trained on, so emulation is reliable for SPIKE's own base model and degrades
gracefully elsewhere. Parsing is strict: malformed calls are surfaced as text, never guessed.
"""

from __future__ import annotations

import json
import re
import uuid

from spike.core.types import Message, ToolCall, ToolSpec

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def tools_system_prompt(tools: list[ToolSpec]) -> str:
    specs = "\n".join(
        json.dumps({"name": t.name, "description": t.description, "parameters": t.parameters}, ensure_ascii=False)
        for t in tools
    )
    return (
        "# Tools\n\nYou may call one or more functions to assist with the user query.\n"
        "Function signatures are provided within <tools></tools> XML tags:\n<tools>\n"
        f"{specs}\n</tools>\n\n"
        "For each function call, return a JSON object with the function name and arguments within "
        '<tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n'
        "</tool_call>\nOnly call a tool when it is needed. After a tool result arrives, continue the answer."
    )


def _parse_one(payload: str) -> ToolCall | None:
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
        return None
    args = obj.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    return ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=obj["name"], arguments=args)


def parse_tool_calls(text: str) -> tuple[str, list[ToolCall], list[str]]:
    """Split model output into (visible text, well-formed tool calls, malformed call blocks).

    Malformed blocks stay in the visible text so nothing the model wrote is silently dropped.
    """
    calls: list[ToolCall] = []
    malformed: list[str] = []

    def _take(match: re.Match[str]) -> str:
        call = _parse_one(match.group(1))
        if call is None:
            malformed.append(match.group(0))
            return match.group(0)
        calls.append(call)
        return ""

    visible = TOOL_CALL_RE.sub(_take, text)
    return visible.strip(), calls, malformed


def flatten_tool_messages(messages: list[Message]) -> list[Message]:
    """Rewrite tool-call/tool-result turns as plain text for APIs without tool roles."""
    out: list[Message] = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            calls = "\n".join(
                "<tool_call>\n" + json.dumps({"name": c.name, "arguments": c.arguments}, ensure_ascii=False) + "\n</tool_call>"
                for c in m.tool_calls
            )
            out.append(Message(role="assistant", content=(m.content + "\n" + calls).strip()))
        elif m.role == "tool":
            out.append(Message(role="user", content=f"<tool_response name=\"{m.name}\">\n{m.content}\n</tool_response>"))
        else:
            out.append(m)
    return out


class StreamingToolFilter:
    """Hide `<tool_call>` blocks from a live text stream while buffering them for parsing."""

    OPEN, CLOSE = "<tool_call>", "</tool_call>"

    def __init__(self) -> None:
        self.buffer = ""
        self.raw = ""
        self.in_call = False

    def feed(self, chunk: str) -> str:
        self.raw += chunk
        self.buffer += chunk
        visible = ""
        while True:
            if self.in_call:
                idx = self.buffer.find(self.CLOSE)
                if idx < 0:
                    return visible
                self.buffer = self.buffer[idx + len(self.CLOSE):]
                self.in_call = False
            else:
                idx = self.buffer.find(self.OPEN)
                if idx >= 0:
                    visible += self.buffer[:idx]
                    self.buffer = self.buffer[idx + len(self.OPEN):]
                    self.in_call = True
                    continue
                # keep a possible partial opening tag in the buffer
                keep = 0
                for k in range(1, len(self.OPEN)):
                    if self.buffer.endswith(self.OPEN[:k]):
                        keep = k
                visible += self.buffer[: len(self.buffer) - keep]
                self.buffer = self.buffer[len(self.buffer) - keep:]
                return visible

    def flush(self) -> str:
        """Return held-back text. An unclosed call block is returned verbatim so it is not lost."""
        rest = (self.OPEN + self.buffer) if self.in_call else self.buffer
        self.buffer = ""
        self.in_call = False
        return rest
