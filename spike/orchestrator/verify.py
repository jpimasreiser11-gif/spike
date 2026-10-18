"""The verifier of a multi-step plan (Collective).

After the team's subtasks run, one more model call checks each result against its instruction, the user's request
and, in Forge, the acceptance criteria the user approved. A result with a concrete problem goes back to its
specialist with the verifier's note (and the subtasks that used it run again too), at most MAX_ROUNDS times; the
integrator then merges the results. Whether a deliverable file was saved is checked by SPIKE itself, not by the
model, and a missing one always sends its subtask back. When the verifier's answer is not valid JSON nothing is sent
back and the run says the results could not be verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spike.orchestrator.planner import Subtask, extract_json

MAX_ROUNDS = 2  # times work can be sent back
RESULT_CHARS = 3000  # of each result shown to the verifier
MIN_FIX = 8  # a "not ok" without a usable note is not sent back: there would be nothing to fix

VERIFIER_PROMPT = (
    "You are the checker of SPIKE, a team of specialist models. Check each subtask result against its instruction "
    "and the user's request{criteria}. Mark a result not ok only for a concrete problem its author can fix: a part "
    "of the instruction that is missing, a calculation or fact that is wrong (say which and why), a contradiction "
    "with another result, or a file it had to save that is missing. Style is not a problem. For each problem write "
    "in `fix` exactly what to change. Reply with JSON only."
)


@dataclass
class Verdict:
    method: str  # "llm" | "unavailable"
    returned: dict[str, str] = field(default_factory=dict)  # subtask id -> what to fix
    criteria: list[dict[str, Any]] = field(default_factory=list)  # Forge: {"text", "ok" (None: not checked), "note"}
    note: str = ""

    def event(self, round_: int, checks: list[dict[str, Any]]) -> dict[str, Any]:
        return {"type": "verify", "round": round_, "method": self.method, "note": self.note,
                "returned": [{"subtask": k, "fix": v} for k, v in self.returned.items()],
                "criteria": self.criteria, "checks": checks}


def verify_schema(ids: list[str], n_criteria: int) -> dict[str, Any]:
    props: dict[str, Any] = {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string", "enum": ids}, "ok": {"type": "boolean"}, "fix": {"type": "string"}},
        "required": ["id", "ok", "fix"], "additionalProperties": False}}}
    if n_criteria:
        props["criteria"] = {"type": "array", "items": {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": n_criteria}, "ok": {"type": "boolean"},
                           "note": {"type": "string"}},
            "required": ["n", "ok", "note"], "additionalProperties": False}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def verifier_prompt(criteria: list[str]) -> str:
    extra = (" and the acceptance criteria; for each criterion say in `criteria` whether the results meet it"
             if criteria else "")
    shape = ('{"results": [{"id": "t1", "ok": true, "fix": ""}]' +
             (', "criteria": [{"n": 1, "ok": true, "note": ""}]}' if criteria else "}"))
    return VERIFIER_PROMPT.format(criteria=extra) + "\n" + shape


def verify_message(user_text: str, subtasks: list[Subtask], results: dict[str, str], names: dict[str, str],
                   criteria: list[str], checks: list[dict[str, Any]]) -> str:
    parts = [f"# User request\n{user_text}"]
    if criteria:
        parts.append("# Acceptance criteria\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1)))
    for t in subtasks:
        text = results.get(t.id, "")
        clipped = text[:RESULT_CHARS] + (" […]" if len(text) > RESULT_CHARS else "")
        files = f"\nFiles it had to save: {', '.join(t.deliverables)}" if t.deliverables else ""
        parts.append(f"## {t.id} · {names.get(t.specialist, t.specialist)} · {t.role}\nInstruction: "
                     f"{t.instruction}{files}\nResult:\n{clipped}")
    if checks:
        parts.append("# Files checked by SPIKE\n" + "\n".join(
            f"- {c['path']} ({c['subtask']}): {'saved, ' + str(c['bytes']) + ' bytes' if c['ok'] else 'NOT FOUND'}"
            for c in checks))
    return "\n\n".join(parts)


def parse_verdict(text: str, ids: list[str], criteria: list[str]) -> Verdict | None:
    obj = extract_json(text)
    if not obj or not isinstance(obj.get("results"), list):
        return None
    returned: dict[str, str] = {}
    for row in obj["results"]:
        if not isinstance(row, dict) or row.get("id") not in ids:
            continue
        fix = str(row.get("fix") or "").strip()
        if row.get("ok") is False and len(fix) >= MIN_FIX:
            returned[str(row["id"])] = fix[:1000]
    judged: dict[int, dict[str, Any]] = {}
    for row in obj.get("criteria") or []:
        if isinstance(row, dict) and isinstance(row.get("n"), int) and 1 <= row["n"] <= len(criteria) \
                and isinstance(row.get("ok"), bool):
            judged[row["n"]] = {"ok": row["ok"], "note": str(row.get("note") or "")[:500]}
    rows = [{"text": c, **judged.get(i, {"ok": None, "note": ""})} for i, c in enumerate(criteria, 1)]
    return Verdict(method="llm", returned=returned, criteria=rows)


def file_checks(subtasks: list[Subtask], root: Path | None) -> list[dict[str, Any]]:
    """Whether each deliverable was saved (and is not empty) in the folder the file tools write to."""
    if root is None:
        return []
    out = []
    for t in subtasks:
        for path in t.deliverables:
            target = (root / path).resolve()
            size = target.stat().st_size if target.is_file() and root in target.parents else 0
            out.append({"subtask": t.id, "path": path, "ok": size > 0, "bytes": size})
    return out


def dependents(subtasks: list[Subtask], ids: set[str]) -> set[str]:
    """These subtasks and every subtask that used their results, directly or not."""
    out = set(ids)
    changed = True
    while changed:
        changed = False
        for t in subtasks:
            if t.id not in out and any(d in out for d in t.depends_on):
                out.add(t.id)
                changed = True
    return out
