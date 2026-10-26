"""Tool strategy learning (Evolution EV3): which tool or skill worked for which kind of task, kept only as counts.

Every chat run records one row per tool call and per skill used. The task type is the specialist that did the step
plus a coarse intent worked out from the user's words by fixed patterns (`intent_of`, no model). A use counts as a
success only if all three hold: the tool returned without an error (a skill: the run ended without one), the user did
not retry the answer or undo the step, and the user did not correct the answer afterwards. Uses the user refused or
denied are not recorded, since they say nothing about the tool. Nothing but names, task types and flags is kept.

The counts are used in one place and only to break a tie. When the skill router has several skills that score the
same (`SKILL_MARGIN`; scores are whole numbers, so 0 means exactly equal), and every one of them has at least
`MIN_SAMPLES` recorded uses for this task type, the one with the best success rate goes first. Rates are compared in
steps of 10 points (Laplace-smoothed), so a tie in rate keeps the router's own order, and a skill below the router's
minimum score is never promoted. SPIKE has no ranking of tools to break a tie in (the model picks them), so tool
counts are only recorded and shown.

The rule that is used is a snapshot of the counts, made when the user asks (or every `AUTO_EVERY` new uses, if
automatic) and kept as a version of the `strategy` component only if routing on `skill_labeled.jsonl` does not get
worse with it and the rest of `spike evolve check` passes with it applied. Rolling back or resetting returns to the
router's own order."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.evolution.store import EvolutionStore
from spike.orchestrator.router import normalize
from spike.skills.engine import SkillLibrary

COMPONENT = "strategy"
MIN_SAMPLES = 5  # recorded uses a skill needs, for one task type, before its counts can change anything
SKILL_MARGIN = 0.0  # scores this close to the best count as tied (skill scores are whole numbers)
STEP = 0.1  # success rates are compared in steps of 10 points
AUTO_EVERY = 20  # new uses between automatic snapshots, when the user left that on
SKILL_LABELED = Path(__file__).with_name("skill_labeled.jsonl")

# (intent, pattern over accent-free lower case), first match wins
INTENTS: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(pattern)) for name, pattern in [
    ("translate", r"\b(traduce|traducir|traduccion|translate|translation)\b"),
    ("summarize", r"\b(resume|resumen|resumir|resumeme|summari[sz]e|summary|sintetiza|tl;?dr)\b"),
    ("code", r"\b(codigo|code|funcion|function|bug|script|python|javascript|typescript|rust|golang|java|compila|"
            r"refactor\w*|traceback|stack ?trace|debug|depura\w*|unit test|test unitario)\b"),
    ("data", r"\b(csv|excel|xlsx|spreadsheet|hoja de calculo|tabla|table|dataset|datos|data|sql|grafico|chart|plot|"
             r"estadistic\w*|statistic\w*|pivot)\b"),
    ("calculate", r"\b(calcula\w*|calculate|cuanto es|how much is|suma|resta|multiplica|divide|porcentaje|percent\w*|"
                  r"interes|interest|iva|vat|roi|roe|ebitda|npv|irr)\b|\d\s*[-+*/x×]\s*\d|\d\s?%"),
    ("document", r"\b(docx|word|pptx|powerpoint|presentacion|slides|diapositivas|pdf|informe|report|documento|"
                 r"document|contrato|contract|carta)\b"),
    ("lookup", r"\b(busca\w*|search|encuentra|find|noticias|news|latest|ultimas?|hoy|today|current|actual|precio de|"
               r"price of|cotizacion)\b|https?://|www\."),
    ("plan", r"\b(plan|planifica\w*|roadmap|estrategia|strategy|calendario|schedule|checklist|pasos|steps)\b"),
    ("write", r"\b(escribe|redacta\w*|write|draft|email|correo|mensaje|message|post|articulo|article|poema|poem|"
              r"historia|story)\b"),
    ("explain", r"\b(explica\w*|explain|que es|what is|como funciona|how does|por que|why|diferencia entre|"
                r"difference between)\b"),
]]
# what a tool result says when the tool was not the one that failed: the user said no, a policy refused the call, or
# the call never reached the tool (agent/loop.py and call_tool write these)
NOT_THE_TOOL = re.compile(r"^error: (refused|the user (denied|has disabled)|tool '.*' is not available|"
                          r"'.*' needs the user's approval)", re.I)


def intent_of(text: str) -> str:
    """A coarse, fixed-pattern intent of a request: translate, summarize, code, data, calculate, document, lookup,
    plan, write, explain or other."""
    norm = normalize(text)
    return next((name for name, pattern in INTENTS if pattern.search(norm)), "other")


def task_type(specialist: str, text: str) -> str:
    return f"{specialist or 'core'}:{intent_of(text)}"


def _blamed(content: str) -> bool:
    """Can this result count for or against the tool? A refusal or a call the user denied says nothing about it."""
    return not NOT_THE_TOOL.match((content or "").lstrip())


def observations(meta: dict[str, Any], question: str, message: str) -> list[dict[str, Any]]:
    """The rows to record for one finished run (`meta` is what the chat stored with the answer)."""
    routed = [s["id"] for s in (meta.get("route") or {}).get("specialists") or [] if s.get("id")]
    first = routed[0] if routed else "core"
    rows: list[dict[str, Any]] = []
    calls = {ev.get("id"): ev for ev in meta.get("tools") or [] if ev.get("type") == "tool_call"}
    for ev in meta.get("tools") or []:
        if ev.get("type") != "tool_result" or not _blamed(ev.get("content") or ""):
            continue
        call = calls.get(ev.get("id")) or {}
        spec = ev.get("specialist") or call.get("specialist") or first
        if ev.get("name") == "load_skill":  # a model that chose its skill: that is a skill use
            name = str((call.get("arguments") or {}).get("name") or "")
            if name:
                rows.append({"message": message, "call": str(ev.get("id") or ""), "kind": "skill", "name": name,
                             "task_type": task_type(spec, question), "ok": bool(ev.get("ok"))})
            continue
        rows.append({"message": message, "call": str(ev.get("id") or ""), "kind": "tool", "name": str(ev.get("name")),
                     "task_type": task_type(spec, question), "ok": bool(ev.get("ok"))})
    events = [ev for ev in meta.get("events") or [] if ev.get("type") == "skill"]
    if not events and meta.get("skills"):
        events = [{"names": meta["skills"], "specialist": first}]
    run_ok = not meta.get("error") and not meta.get("cancelled")
    seen: set[tuple[str, str]] = set()
    for ev in events:
        for name in ev.get("names") or []:
            spec = ev.get("specialist") or first
            if (name, spec) not in seen:
                seen.add((name, spec))
                rows.append({"message": message, "call": "", "kind": "skill", "name": str(name),
                             "task_type": task_type(spec, question), "ok": run_ok})
    return rows


# ------------------------------------------------------------------ using the counts
def smoothed(good: int, n: int) -> float:
    return (good + 1) / (n + 2)


def bucket(good: int, n: int) -> int:
    return math.floor(smoothed(good, n) / STEP + 1e-9)


def reorder(ranked: list[tuple[float, str]], rates: dict[str, list[int]], margin: float = SKILL_MARGIN,
            min_samples: int = MIN_SAMPLES) -> list[str]:
    """Names of `ranked` ((score, name), best first) in the order to use. Only the names whose score is within
    `margin` of the best can move, only among themselves, and only if every one of them has `min_samples` recorded
    uses in `rates` (name -> [successes, uses]); otherwise the router's order stays."""
    names = [name for _, name in ranked]
    if len(ranked) < 2:
        return names
    top = ranked[0][0]
    tied = [name for score, name in ranked if score >= top - margin]
    if len(tied) < 2 or any(rates.get(name, [0, 0])[1] < min_samples for name in tied):
        return names
    return sorted(tied, key=lambda name: -bucket(*rates[name])) + names[len(tied):]  # sorted() is stable


@dataclass(frozen=True)
class Preference:
    """A snapshot of skill counts: task type -> skill -> [successes, uses]."""

    skills: dict[str, dict[str, list[int]]]
    margin: float = SKILL_MARGIN
    min_samples: int = MIN_SAMPLES

    @classmethod
    def from_stats(cls, stats: list[dict[str, Any]], min_samples: int = MIN_SAMPLES) -> Preference:
        skills: dict[str, dict[str, list[int]]] = {}
        for r in stats:
            if r["kind"] == "skill" and r["n"] >= min_samples:
                skills.setdefault(r["task_type"], {})[r["name"]] = [r["good"], r["n"]]
        return cls(skills, SKILL_MARGIN, min_samples)

    @classmethod
    def from_version(cls, data: dict[str, Any]) -> Preference:
        return cls({t: {n: list(v) for n, v in names.items()} for t, names in (data.get("skills") or {}).items()},
                   float(data.get("margin", SKILL_MARGIN)), int(data.get("min_samples", MIN_SAMPLES)))

    def to_dict(self) -> dict[str, Any]:
        return {"skills": self.skills, "margin": self.margin, "min_samples": self.min_samples}

    def order(self, ranked: list[tuple[float, str]], specialist: str, text: str) -> list[str]:
        return reorder(ranked, self.skills.get(task_type(specialist, text), {}), self.margin, self.min_samples)


@contextmanager
def preferring(library: SkillLibrary, preference: Preference | None) -> Iterator[None]:
    """Use a preference for the skill router inside the block (to check it before it is kept)."""
    before = library.prefer
    library.prefer = preference.order if preference else None
    try:
        yield
    finally:
        library.prefer = before


# ------------------------------------------------------------------ the gate
def load_skill_labeled() -> list[dict[str, Any]]:
    return [json.loads(line) for line in SKILL_LABELED.read_text(encoding="utf-8").splitlines() if line.strip()]


def skill_routing(library: SkillLibrary, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """How many labelled requests the skill router answers as labelled (the skill, or no skill) with the library's
    current order."""
    rows = load_skill_labeled() if rows is None else rows
    wrong = [r["query"] for r in rows
             if [s.name for s in library.select(r["query"], r["specialist"])] != ([r["expected"]] if r["expected"] else [])]
    return {"n": len(rows), "correct": len(rows) - len(wrong), "wrong": wrong}


def compare_routing(library: SkillLibrary, preference: Preference | None) -> dict[str, Any]:
    """Skill routing without and with a preference: `ok` unless the preference makes it worse."""
    with preferring(library, None):  # the router's own order, whatever preference is live
        before = skill_routing(library)
    if preference is None:
        return {"ok": True, "before": before, "after": before}
    with preferring(library, preference):
        after = skill_routing(library)
    return {"ok": after["correct"] >= before["correct"], "before": before, "after": after}


def table(store: EvolutionStore, min_samples: int = MIN_SAMPLES) -> list[dict[str, Any]]:
    """The recorded counts for Settings → Evolución: one row per tool or skill and task type."""
    return [{**r, "rate": round(r["good"] / r["n"], 3) if r["n"] else None, "enough": r["n"] >= min_samples}
            for r in store.run_stats()]


def learn(store: EvolutionStore, library: SkillLibrary, gate: Callable[[Preference], tuple[bool, str]] | None = None,
          min_samples: int = MIN_SAMPLES) -> dict[str, Any]:
    """Snapshot the counts as the rule for tie-breaks, and keep it (as a version of `strategy`) only if skill routing
    does not get worse with it and `gate` (the rest of the regression checks, run with it applied) passes. Every
    attempt that changes something is kept in the history, accepted or not."""
    stats = store.run_stats()
    preference = Preference.from_stats(stats, min_samples)
    report: dict[str, Any] = {"uses": sum(r["n"] for r in stats), "task_types": len(preference.skills),
                              "skills": sum(len(v) for v in preference.skills.values()), "min_samples": min_samples,
                              "margin": preference.margin, "accepted": False, "reasons": []}
    active = store.active(COMPONENT)
    if not preference.skills:
        report["reasons"].append(f"no skill has {min_samples} recorded uses for one task type yet")
        return {**report, "version": None}
    if active and Preference.from_version(active["data"]) == preference:
        return {**report, "accepted": True, "version": active["id"], "unchanged": True}
    routing = compare_routing(library, preference)
    report["routing"] = {"before": routing["before"]["correct"], "after": routing["after"]["correct"],
                         "n": routing["before"]["n"], "wrong_after": routing["after"]["wrong"]}
    if not routing["ok"]:
        report["reasons"].append(f"skill routing gets worse with it ({routing['before']['correct']}/"
                                 f"{routing['before']['n']} -> {routing['after']['correct']}/{routing['after']['n']})")
    elif gate is not None:
        ok, detail = gate(preference)
        if not ok:
            report["reasons"].append(f"regression checks fail with it applied: {detail}")
    report["accepted"] = not report["reasons"]
    reason = (f"tie-break from {report['uses']} recorded uses ({report['skills']} skills, {report['task_types']} task "
              f"types)" if report["accepted"] else "rejected: " + "; ".join(report["reasons"]))
    version = store.add_version(COMPONENT, preference.to_dict(), report, reason, activate=report["accepted"])
    return {**report, "version": version["id"]}


def active_preference(store: EvolutionStore) -> Preference | None:
    version = store.active(COMPONENT)
    return Preference.from_version(version["data"]) if version else None


def reset(store: EvolutionStore) -> int:
    """Forget every recorded use and go back to the router's own order (the versions stay in the history)."""
    store.deactivate(COMPONENT)
    return store.clear_runs()
