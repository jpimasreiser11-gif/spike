"""Agent loop: model call -> tool calls (permission-gated) -> tool results -> model call, until an answer. The last
allowed call is told to answer without tools, so a run that reaches the step limit still reports what it did."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from spike.core.context import fit_messages
from spike.core.types import ChatRequest, Message, ToolCall
from spike.providers.base import Provider
from spike.tools.base import PermissionBroker, Tool
from spike.tools.builtin import NO_ONE_TO_ASK, AskUser

Event = dict[str, Any]
LAST_STEP = ("[SPIKE] This is your last step: do not call any more tools. Reply now with your final answer: what "
             "you did, which files you saved and anything left undone.")


class Checkpointer(Protocol):
    """Keeps a copy of the files a tool is about to change (see spike/store/checkpoints.py)."""

    def before(self, call_id: str, tool: str, paths: list[Path]) -> str | None: ...
    def after(self, checkpoint_id: str) -> None: ...


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
    checkpoints: Checkpointer | None = None,
) -> AsyncIterator[Event]:
    """Stream UI events. `tag` is merged into every event (e.g. {"subtask": "t1"})."""
    tag = tag or {}
    by_name = {t.name: t for t in tools}
    history = list(messages)

    for step in range(max_steps):
        run.steps = step + 1
        last = step == max_steps - 1
        if last and history and history[-1].role == "tool":
            history[-1] = replace(history[-1], content=f"{history[-1].content}\n\n{LAST_STEP}")
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
        refused = last and bool(calls)
        if refused:  # calls past the limit are not run, so the answer does not keep them
            calls = []
        assistant = Message(role="assistant", content=text, tool_calls=calls)
        history.append(assistant)
        run.messages.append(assistant)
        run.text += text
        if not calls:
            if refused and not text.strip():
                break
            return

        for call in calls:
            yield {"type": "tool_call", "id": call.id, "name": call.name, "arguments": call.arguments, **tag}
            tool = by_name.get(call.name)
            # a workspace file the tool wrote; parts of the result that are file contents; the copy kept to undo it;
            # something for the app to show (a real-order proposal to confirm)
            file, private, checkpoint, ui = None, [], None, None
            if tool is None:
                result_text, ok = f"error: tool '{call.name}' is not available to this specialist", False
            elif tool.name == AskUser.name:
                question = str(call.arguments.get("question") or "").strip()
                options = [str(o).strip()[:200] for o in call.arguments.get("options") or [] if str(o).strip()][:6]
                if not question:
                    result_text, ok = "error: 'question' is required", False
                elif not broker.interactive:
                    result_text, ok = NO_ONE_TO_ASK, False
                else:
                    q = broker.ask(question[:2000], options)
                    yield {"type": "question", "id": q.id, "question": q.text, "options": options,
                           "call_id": call.id, **tag}
                    answer = await broker.wait_answer(q)
                    yield {"type": "answered", "id": q.id, "answer": answer, **tag}
                    result_text, ok = (f"The user answered: {answer}", True) if answer is not None else \
                        ("The user did not answer in time; continue with your best assumption and say what you "
                         "assumed.", False)
            else:
                outcome: list[Any] = []
                async for ev in call_tool(tool, call, broker, checkpoints, tag, outcome):
                    yield ev
                result_text, ok, file, private, checkpoint, ui = outcome
            yield {"type": "tool_result", "id": call.id, "name": call.name, "ok": ok, "content": result_text[:4000],
                   **({"file": file} if file else {}), **({"checkpoint": checkpoint} if checkpoint and ok else {}),
                   **({"ui": ui} if ui else {}), **tag}
            tool_msg = Message(role="tool", content=result_text, tool_call_id=call.id, name=call.name, private=private)
            history.append(tool_msg)
            run.messages.append(tool_msg)

    run.error = f"stopped after {max_steps} tool steps without a final answer"
    yield {"type": "error", "message": run.error, **tag}


async def call_tool(tool: Tool, call: ToolCall, broker: PermissionBroker, checkpoints: Checkpointer | None,
                    tag: dict[str, Any], outcome: list[Any]) -> AsyncIterator[Event]:
    """Run one tool call if the broker's policy lets it, asking the user first when the policy says ask. Yields the
    permission events; leaves (text, ok, file, private, checkpoint, ui) in `outcome`. Everything SPIKE runs for a
    model goes through here, the checks Forge runs on saved files included."""
    refused = None
    policy, review = broker.policy_for_call(tool, call.arguments)
    if policy == "deny":
        refused = (f"error: refused: {review.reason}" if review and review.policy == "deny"
                   else f"error: the user has disabled the '{call.name}' tool")
    elif policy == "ask" and not broker.interactive:
        refused = (f"error: '{call.name}' needs the user's approval, which can only be given in "
                   "the SPIKE app; it is not available to this caller")
    elif policy == "ask":
        # Yield the request first: the consumer forwards it to the UI before we block on it.
        req = broker.open(tool, call.arguments, review)
        yield {"type": "permission_request", "id": req.id, "tool": tool.name, "risk": tool.risk,
               "arguments": call.arguments, "call_id": call.id, **tag,
               **({"reason": review.reason, "code": review.code, "once": review.once, "domain": review.domain}
                  if review and review.policy == "ask" else {})}
        decision = await broker.wait(req)
        yield {"type": "permission_resolved", "id": req.id, "decision": decision, **tag}
        if decision == "deny":
            refused = "error: the user denied this tool call"
    outcome[:] = (refused, False, None, [], None, None) if refused else await _execute(tool, call, checkpoints)


async def _execute(tool: Tool, call: ToolCall, checkpoints: Checkpointer | None
                   ) -> tuple[str, bool, str | None, list[str], str | None, dict[str, Any] | None]:
    checkpoint = checkpoints.before(call.id, tool.name, tool.targets(call.arguments)) if checkpoints else None
    try:
        result = await tool.run(call.arguments)
    except Exception as exc:  # a tool bug must not kill the conversation
        return f"error: {exc.__class__.__name__}: {exc}", False, None, [], None, None
    finally:
        if checkpoint and checkpoints:
            checkpoints.after(checkpoint)
    file = result.data.get("file") if result.ok else None
    ui = result.data.get("ui") if result.ok and isinstance(result.data.get("ui"), dict) else None
    return (result.content, result.ok, file if isinstance(file, str) else None, [p for p in result.private if p],
            checkpoint, ui)
