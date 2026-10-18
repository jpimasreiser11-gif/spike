"""Context-window budgeting.

Keeps the system prompt and the most recent turns, drops the oldest turns first and leaves an explicit
marker so the model knows history was trimmed. Token counts use a conservative character heuristic unless
an exact tokenizer callback is supplied (llama-server exposes /tokenize).
"""

from __future__ import annotations

from collections.abc import Callable

from spike.core.types import Message

CHARS_PER_TOKEN = 3.0  # conservative for mixed English/Spanish/code; overestimates tokens on purpose
MESSAGE_OVERHEAD = 6


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def message_tokens(m: Message, counter: Callable[[str], int] = estimate_tokens) -> int:
    total = counter(m.content) + MESSAGE_OVERHEAD
    for call in m.tool_calls:
        total += counter(call.name) + counter(str(call.arguments))
    return total


def fit_messages(
    messages: list[Message],
    budget_tokens: int,
    counter: Callable[[str], int] = estimate_tokens,
) -> tuple[list[Message], int]:
    """Return (messages that fit the budget, number of dropped messages).

    System messages and the final message are always kept. A tool result is never kept without the
    assistant turn that requested it, so the provider never sees an orphaned tool message.
    """
    if not messages:
        return [], 0
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    used = sum(message_tokens(m, counter) for m in system)
    kept: list[Message] = []
    for m in reversed(rest):
        cost = message_tokens(m, counter)
        if kept and used + cost > budget_tokens:
            break
        kept.append(m)
        used += cost
    kept.reverse()
    while kept and kept[0].role == "tool" and len(kept) > 1:
        kept.pop(0)
    dropped = len(rest) - len(kept)
    if dropped:
        note = Message(role="system", content=f"[{dropped} earlier messages were omitted to fit the context window.]")
        return system + [note] + kept, dropped
    return system + kept, 0
