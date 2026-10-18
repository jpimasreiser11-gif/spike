"""Evolution level 3: the user's corrections as retraining data, only with their consent.

With Settings → Evolution → "Use my corrections to retrain" on (off by default), each saved correction becomes an
example: the question, the answer given after the correction (chosen) and the answer it corrected (rejected), with
the checks of its eval candidate as acceptance criteria. An example is proposed only if:

- both answers come from SPIKE's own local engine: never from an external API (their terms can forbid training on
  their outputs) nor from another local model (its license may restrict it);
- the chosen answer finished without an error and passes the checks, and the rejected one fails them, when the
  candidate has checks;
- it is not already an example.

The user approves or rejects each one; approved examples export as chat JSONL (`training/prepare.py --corrections`)
and as preference pairs for a DPO pass. Nothing leaves the computer unless the user moves the file.
"""

from __future__ import annotations

import json
from typing import Any

from spike.evolution.candidates import judge

LOCAL_ENGINE = "spike-local"


def _providers(meta: dict[str, Any]) -> list[str]:
    return [s.get("provider_id") or "" for s in (meta.get("route") or {}).get("specialists") or []]


def _origin(message: dict[str, Any]) -> str | None:
    """Why this answer cannot be training data, or None when it can."""
    meta = message.get("meta") or {}
    if meta.get("error") or meta.get("cancelled"):
        return "it ended with an error or was stopped"
    providers = _providers(meta)
    if not providers:
        return "it does not record which model wrote it"
    others = sorted({p for p in providers if p != LOCAL_ENGINE})
    if others:
        return (f"it was written by {', '.join(others)}: only answers from SPIKE's own local model are used, because "
                "other services' terms and other models' licenses can forbid training on their outputs")
    return None


def build(evolution, store, system_prompt) -> dict[str, Any]:
    """Turn saved corrections into examples (proposed or skipped with the reason). `store` holds the chats,
    `system_prompt(specialist)` gives the prompt the example is trained under."""
    made = {"proposed": 0, "skipped": 0, "unchanged": 0}
    candidates = {c.get("source"): c for c in evolution.store.items("candidate") if c.get("from") == "correction"}
    for item in evolution.store.items("correction"):
        existing = evolution.store.find("example", source=item["id"])
        if existing and existing["status"] != "skipped":
            made["unchanged"] += 1
            continue
        if existing:  # skipped before: its chat, checks or answers may have changed since
            evolution.store.delete(existing["id"])
        thread = store.messages(item["conversation"])
        at = next((i for i, m in enumerate(thread) if m["id"] == item["message"]), None)
        if at is None:
            continue  # the chat was deleted
        chosen = next((m for m in thread[at + 1:] if m["role"] == "assistant"), None)
        if chosen is None:
            continue  # no answer after the correction yet: try again later
        rejected = next((m for m in reversed(thread[:at]) if m["role"] == "assistant"), None)
        specialist = (item.get("specialists") or [None])[0]
        candidate = candidates.get(item["id"])
        checks = (candidate or {}).get("checks") or {}
        reason = _origin(chosen) or (_origin(rejected) if rejected else "the corrected answer is gone")
        if reason:
            reason = f"not used: {reason}"
        elif checks.get("include") or checks.get("exclude"):
            ok, problems = judge(chosen["content"], None, checks)
            bad, _ = judge(rejected["content"], None, checks)  # type: ignore[index]
            if not ok:
                reason = "not used: the answer after the correction fails its checks (" + "; ".join(problems) + ")"
            elif bad:
                reason = "not used: the answer that was corrected already passes the checks, so the pair teaches nothing"
        data = {"source": item["id"], "conversation": item["conversation"], "specialist": specialist,
                "system": system_prompt(specialist) if specialist else "", "question": item["question"],
                "chosen": chosen["content"], "rejected": rejected["content"] if rejected else "",
                "rule": item.get("rule"), "checks": checks, "candidate": (candidate or {}).get("id"),
                "reason": reason or ""}
        evolution.store.add("example", data, status="skipped" if reason else "proposed")
        made["skipped" if reason else "proposed"] += 1
    return made


def _chat(e: dict[str, Any], answer: str) -> list[dict[str, str]]:
    return [*([{"role": "system", "content": e["system"]}] if e.get("system") else []),
            {"role": "user", "content": e["question"]}, {"role": "assistant", "content": answer}]


def export_chats(examples: list[dict[str, Any]]) -> str:
    """Approved examples in the mlx-lm chat format, with what the training script needs to filter them."""
    return "".join(json.dumps({"messages": _chat(e, e["chosen"]),
                               "meta": {"id": e["id"], "specialist": e["specialist"], "source": "spike-correction",
                                        "checks": e.get("checks") or {}}}, ensure_ascii=False) + "\n"
                   for e in examples)


def export_pairs(examples: list[dict[str, Any]]) -> str:
    """Approved examples as preference pairs (prompt / chosen / rejected), for a DPO pass after SFT."""
    return "".join(json.dumps({"prompt": _chat(e, "")[:-1], "chosen": [{"role": "assistant", "content": e["chosen"]}],
                               "rejected": [{"role": "assistant", "content": e["rejected"]}],
                               "meta": {"id": e["id"], "specialist": e["specialist"], "source": "spike-correction",
                                        "checks": e.get("checks") or {}}}, ensure_ascii=False) + "\n"
                   for e in examples if e.get("rejected"))
