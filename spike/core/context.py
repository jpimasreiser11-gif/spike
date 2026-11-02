"""Context-window budgeting.

Keeps the system prompt and the most recent turns, drops the oldest turns first and leaves an explicit
marker so the model knows history was trimmed. Token counts use a conservative character heuristic unless
an exact tokenizer callback is supplied (llama-server exposes /tokenize).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from spike.core.types import Message

CHARS_PER_TOKEN = 3.0  # conservative for mixed English/Spanish/code; overestimates tokens on purpose
MESSAGE_OVERHEAD = 6
TRUNCATED = "\n...[tool output truncated to fit the context window]"


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def message_tokens(m: Message, counter: Callable[[str], int] = estimate_tokens) -> int:
    total = counter(m.content) + MESSAGE_OVERHEAD
    for call in m.tool_calls:
        total += counter(call.name) + counter(str(call.arguments))
    return total


def _turns(rest: list[Message]) -> tuple[list[list[Message]], int]:
    """Group messages so an assistant turn with tool calls and its tool results stay together; (turns, orphans dropped)."""
    turns: list[list[Message]] = []
    orphans = 0
    for m in rest:
        if m.role != "tool":
            turns.append([m])
        elif turns and turns[-1][0].tool_calls:
            turns[-1].append(m)
        else:
            orphans += 1  # a tool result whose request is gone: every provider refuses it
    return turns, orphans


def _cut(content: str, budget: int, counter: Callable[[str], int]) -> str:
    """`content` shortened with an explicit marker until it costs at most `budget` (the marker alone if nothing fits)."""
    if counter(content) <= budget:
        return content
    end = len(content)
    while end > 0:
        end = min(end - 1, int(end * max(budget, 0) / max(counter(content[:end] + TRUNCATED), 1)))
        candidate = content[:max(end, 0)] + TRUNCATED
        if counter(candidate) <= budget:
            return candidate
    return TRUNCATED


def _shrink(turn: list[Message], budget: int, counter: Callable[[str], int]) -> list[Message]:
    """The last tool turn alone exceeds the budget: cut its tool results, in copies, sharing the room equally."""
    tools = [m for m in turn if m.role == "tool"]
    if not tools:
        return turn
    fixed = sum(message_tokens(replace(m, content="" if m.role == "tool" else m.content), counter) for m in turn)
    share = max(budget - fixed, 0) // len(tools)
    return [replace(m, content=_cut(m.content, share, counter)) if m.role == "tool" else m for m in turn]


def fit_messages(
    messages: list[Message],
    budget_tokens: int,
    counter: Callable[[str], int] = estimate_tokens,
) -> tuple[list[Message], int]:
    """Return (messages that fit the budget, number of dropped messages).

    System messages and the final turn are always kept. An assistant turn with tool calls and its tool results are kept
    or dropped together, so a provider never sees a tool result without its request or a call without its result; when
    that final turn alone is too long, its tool results are cut (with a marker), in copies.
    """
    if not messages:
        return [], 0
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    used = sum(message_tokens(m, counter) for m in system)
    turns, orphans = _turns(rest)
    cost = [sum(message_tokens(m, counter) for m in t) for t in turns]
    kept: list[list[Message]] = []
    for i in range(len(turns) - 1, -1, -1):
        if not kept and used + cost[i] > budget_tokens:
            # leave room for the short request just before it, or the model sees results of a question it never read
            room = cost[i - 1] if i and cost[i - 1] <= budget_tokens // 4 else 0
            kept.append(_shrink(turns[i], budget_tokens - used - room, counter))
            used += sum(message_tokens(m, counter) for m in kept[-1])
            continue
        if kept and used + cost[i] > budget_tokens:
            break
        kept.append(turns[i])
        used += cost[i]
    flat = [m for t in reversed(kept) for m in t]
    dropped = len(rest) - len(flat)
    if dropped:
        note = Message(role="system", content=f"[{dropped} earlier messages were omitted to fit the context window.]")
        return system + [note] + flat, dropped
    return system + flat, 0
