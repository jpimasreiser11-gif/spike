"""Agent loop: model call -> tool calls (permission-gated) -> tool results -> model call, until an answer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from spike.core.context import fit_messages
from spike.core.types import ChatRequest, Message, ToolCall
from spike.providers.base import Provider
from spike.tools.base import PermissionBroker, Tool

Event = dict[str, Any]


@dataclass
class AgentRun:
    """Result of one agent run, filled while events are streamed."""

    text: str = ""
    reasoning: str = ""
    messages: list[Message] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    steps: int = 0
    finish_reason: str | None = None  # of the last model call ("length" = cut by max_tokens)
    private: bool = False  # the model saw the user's file contents, so what it wrote may quote them


async def run_agent(
    provider: Provider,
    messages: list[Message],
    *,
    tools: list[Tool],
    broker: PermissionBroker,
    run: AgentRun,
    adapter: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    context_budget: int = 24_000,
    max_steps: int = 8,
    reasoning: bool | None = None,
    tag: dict[str, Any] | None = None,
) -> AsyncIterator[Event]:
    """Stream UI events. `tag` is merged into every event (e.g. {"subtask": "t1"})."""
    tag = tag or {}
    by_name = {t.name: t for t in tools}
    history = list(messages)

    for step in range(max_steps):
        run.steps = step + 1
        fitted, dropped = fit_messages(history, context_budget)
        # only a model that actually gets the files can quote them (a guarded provider may withhold them)
        run.private = run.private or (getattr(provider, "receives_files", True) and any(m.private for m in fitted))
        if dropped:
            yield {"type": "context_trimmed", "dropped": dropped, **tag}
        request = ChatRequest(
            messages=fitted, model=model, adapter=adapter, temperature=temperature, max_tokens=max_tokens,
            tools=[t.spec() for t in tools], reasoning=reasoning,
        )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        async for ev in provider.stream(request):
            if ev.kind == "text":
                text_parts.append(ev.text)
                yield {"type": "delta", "text": ev.text, **tag}
            elif ev.kind == "reasoning":
                run.reasoning += ev.text
                yield {"type": "reasoning", "text": ev.text, **tag}
            elif ev.kind == "tool_call" and ev.tool_call:
                calls.append(ev.tool_call)
            elif ev.kind == "usage" and ev.usage:
                run.usage.append(ev.usage)
                yield {"type": "usage", "usage": ev.usage, **tag}
            elif ev.kind == "notice" and ev.notice:
                yield {**ev.notice, **tag}
            elif ev.kind == "done":
                run.finish_reason = ev.finish_reason
            elif ev.kind == "error":
                run.error = ev.text
                yield {"type": "error", "message": ev.text, **tag}
                return
        text = "".join(text_parts)
        assistant = Message(role="assistant", content=text, tool_calls=calls)
        history.append(assistant)
        run.messages.append(assistant)
        run.text += text
        if not calls:
            return

        for call in calls:
            yield {"type": "tool_call", "id": call.id, "name": call.name, "arguments": call.arguments, **tag}
            tool = by_name.get(call.name)
            file, private = None, []  # a workspace file the tool wrote; parts of the result that are file contents
            if tool is None:
                result_text, ok = f"error: tool '{call.name}' is not available to this specialist", False
            else:
                policy = broker.policy_for(tool)
                if policy == "deny":
                    result_text, ok = f"error: the user has disabled the '{call.name}' tool", False
                elif policy == "ask" and not broker.interactive:
                    result_text, ok = (f"error: '{call.name}' needs the user's approval, which can only be given in "
                                       "the SPIKE app; it is not available to this caller"), False
                elif policy == "ask":
                    # Yield the request first: the consumer forwards it to the UI before we block on it.
                    req = broker.open(tool, call.arguments)
                    yield {"type": "permission_request", "id": req.id, "tool": tool.name, "risk": tool.risk,
                           "arguments": call.arguments, "call_id": call.id, **tag}
                    decision = await broker.wait(req)
                    yield {"type": "permission_resolved", "id": req.id, "decision": decision, **tag}
                    if decision == "deny":
                        result_text, ok = "error: the user denied this tool call", False
                    else:
                        result_text, ok, file, private = await _execute(tool, call)
                else:
                    result_text, ok, file, private = await _execute(tool, call)
            yield {"type": "tool_result", "id": call.id, "name": call.name, "ok": ok, "content": result_text[:4000],
                   **({"file": file} if file else {}), **tag}
            tool_msg = Message(role="tool", content=result_text, tool_call_id=call.id, name=call.name, private=private)
            history.append(tool_msg)
            run.messages.append(tool_msg)

    run.error = f"stopped after {max_steps} tool steps without a final answer"
    yield {"type": "error", "message": run.error, **tag}


async def _execute(tool: Tool, call: ToolCall) -> tuple[str, bool, str | None, list[str]]:
    try:
        result = await tool.run(call.arguments)
    except Exception as exc:  # a tool bug must not kill the conversation
        return f"error: {exc.__class__.__name__}: {exc}", False, None, []
    file = result.data.get("file") if result.ok else None
    return result.content, result.ok, file if isinstance(file, str) else None, [p for p in result.private if p]
