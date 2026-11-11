"""The events of one run as SPIKE keeps them with the answer, for the step-by-step view and the task space: consecutive
text pieces merged into one event, at most MAX_RUN_EVENTS, each with its time since the run started. The app's chat
and Dev sessions keep them the same way (`web/src/run.ts` `recordEvent` is the same rule for a live run)."""

from __future__ import annotations

from typing import Any

MAX_RUN_EVENTS = 3000  # events kept per answer


def record_event(events: list[dict[str, Any]], ev: dict[str, Any], t: float) -> None:
    """Append `ev` (seen `t` seconds after the run started) to `events`, merging it into the last event when both are
    text of the same kind, subtask and mind."""
    last = events[-1] if events else None
    if (ev["type"] in ("delta", "reasoning") and last and last["type"] == ev["type"]
            and last.get("subtask") == ev.get("subtask") and last.get("mind") == ev.get("mind")):
        last["text"] += ev["text"]
    elif len(events) < MAX_RUN_EVENTS:
        events.append({**ev, "t": round(t, 3)})
