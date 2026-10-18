"""Evolution level 2: a specialist's learned instructions and skills, tuned against the user's own eval.

A variant is a few instruction lines added to the specialist's prompt and a mode per skill (`always` or `off`; the
router decides otherwise). The ideas to try are the rules the user saved from corrections for that specialist, the
lines the user types, and the specialist's skills. The search is greedy: each round tries every one-step change
(add a line, drop a line, switch a skill), keeps the change that passes the most eval questions, and stops when
nothing passes more. A change counts only if it passes more questions than the version in use and fails none that
it passed; the winner must hold on a second run, or nothing changes. The eval is the user's accepted candidates
for that specialist that have checks, answered without memory so the gain is the prompt's own. Every attempt is
kept as a version; only one that passed becomes active, and rollback goes back to the one before."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from spike.evolution.store import EvolutionStore
from spike.orchestrator.router import normalize

MIN_QUESTIONS = 3  # fewer questions than this can't tell a better prompt from luck
MAX_CALLS = 120  # model answers one optimisation may use (about an hour for a 4B model on a CPU)
MAX_INSTRUCTIONS = 8
MAX_LINE = 300
SKILL_MODES = ("always", "off")

Answer = Callable[[dict[str, Any], "Variant"], Awaitable[tuple[str, str | None]]]
Progress = Callable[[dict[str, Any]], Awaitable[None]]


def component(specialist: str) -> str:
    return f"prompt:{specialist}"


@dataclass(frozen=True)
class Variant:
    instructions: tuple[str, ...] = ()
    skills: tuple[tuple[str, str], ...] = ()  # sorted (skill, "always" | "off")

    @classmethod
    def of(cls, instructions: list[str] | tuple[str, ...] = (), skills: dict[str, str] | None = None) -> Variant:
        return cls(tuple(instructions), tuple(sorted((k, v) for k, v in (skills or {}).items() if v in SKILL_MODES)))

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Variant:
        data = data or {}
        return cls.of([str(x) for x in data.get("instructions") or []], data.get("skills") or {})

    def to_dict(self) -> dict[str, Any]:
        return {"instructions": list(self.instructions), "skills": dict(self.skills)}

    def skill_modes(self) -> dict[str, str]:
        return dict(self.skills)


def active(store: EvolutionStore, specialist: str) -> Variant:
    version = store.active(component(specialist))
    return Variant.from_dict(version["data"]) if version else Variant()


def learned(store: EvolutionStore, specialists: list[str]) -> dict[str, Variant]:
    """The active variant of each specialist that has one."""
    out = {}
    for spec in specialists:
        version = store.active(component(spec))
        if version:
            out[spec] = Variant.from_dict(version["data"])
    return out


def eval_set(store: EvolutionStore, specialist: str) -> list[dict[str, Any]]:
    """The user's accepted eval questions for this specialist that have checks to apply."""
    return [c for c in reversed(store.items("candidate", "accepted")) if c.get("specialist") == specialist
            and ((c.get("checks") or {}).get("include") or (c.get("checks") or {}).get("exclude"))]


def ideas_for(store: EvolutionStore, specialist: str, typed: list[str] | None = None) -> list[str]:
    """Lines worth trying: the user's own (typed now) first, then the rules saved from corrections of this
    specialist's answers. Duplicates and empty lines go; each line is cut to MAX_LINE characters."""
    lines = [*(typed or []), *(i.get("rule") or "" for i in reversed(store.items("correction"))
                                if specialist in (i.get("specialists") or []))]
    out, seen = [], set()
    for line in lines:
        line = " ".join(str(line).split())[:MAX_LINE]
        key = normalize(line)
        if line and key not in seen:
            seen.add(key)
            out.append(line)
    return out


def moves(current: Variant, ideas: list[str], skills: list[str]) -> list[tuple[str, Variant]]:
    """Every one-step change of a variant."""
    have = {normalize(line) for line in current.instructions}
    modes = current.skill_modes()
    out: list[tuple[str, Variant]] = []
    if len(current.instructions) < MAX_INSTRUCTIONS:
        out += [(f"add: {idea}", Variant.of([*current.instructions, idea], modes))
                for idea in ideas if normalize(idea) not in have]
    out += [(f"remove: {line}", Variant.of([x for x in current.instructions if x != line], modes))
            for line in current.instructions]
    for skill in skills:
        for mode in (*SKILL_MODES, "auto"):
            if modes.get(skill, "auto") != mode:
                out.append((f"skill {skill}: {mode}", Variant.of(current.instructions,
                                                                  {**modes, skill: mode} if mode != "auto" else
                                                                  {k: v for k, v in modes.items() if k != skill})))
    return out


@dataclass
class Score:
    passed: set[str] = field(default_factory=set)
    failed: dict[str, list[str]] = field(default_factory=dict)

    def summary(self, total: int) -> dict[str, Any]:
        return {"passed": len(self.passed), "total": total, "failed": self.failed}


async def score(variant: Variant, questions: list[dict[str, Any]], answer: Answer) -> Score:
    from spike.evolution.candidates import judge

    result = Score()
    for q in questions:
        try:
            text, error = await answer(q, variant)
        except Exception as exc:  # one broken question must not stop the others
            text, error = "", f"{exc.__class__.__name__}: {exc}"
        ok, problems = judge(text, error, q.get("checks") or {})
        if ok:
            result.passed.add(q["id"])
        else:
            result.failed[q["id"]] = problems
    return result


async def optimize(store: EvolutionStore, specialist: str, questions: list[dict[str, Any]], answer: Answer,
                   ideas: list[str], skills: list[str], max_calls: int = MAX_CALLS, progress: Progress | None = None,
                   gate: Callable[[], tuple[bool, str]] | None = None) -> dict[str, Any]:
    """Search for a better variant; the best one becomes active only if it passes the eval rules (module doc)."""
    current = active(store, specialist)
    n = len(questions)
    report: dict[str, Any] = {"specialist": specialist, "questions": n, "accepted": False, "reasons": [], "notes": [],
                              "tried": [], "calls": 0, "measured_without_memory": True}
    if n < MIN_QUESTIONS:
        report["reasons"].append(f"only {n} accepted eval questions with checks for {specialist}; accept at least "
                                 f"{MIN_QUESTIONS} in Settings → Evolution first")
        return {**report, "version": None}

    async def run(label: str, variant: Variant) -> Score:
        if progress:
            await progress({"type": "try", "label": label, "calls": report["calls"]})
        result = await score(variant, questions, answer)
        report["calls"] += n
        return result

    base = await run("in use", current)
    report["baseline"] = base.summary(n)
    best, best_score, path = current, base, []
    while report["calls"] + n <= max_calls:
        round_best: tuple[str, Variant, Score] | None = None
        for label, variant in moves(best, ideas, skills):
            if report["calls"] + n > max_calls:
                report["notes"].append(f"stopped at the budget of {max_calls} answers")
                break
            s = await run(label, variant)
            lost = sorted(best_score.passed - s.passed)
            report["tried"].append({"change": label, "passed": len(s.passed), "lost": lost})
            if not lost and len(s.passed) > len((round_best[2] if round_best else best_score).passed):
                round_best = (label, variant, s)
        if round_best is None:
            break
        path.append(round_best[0])
        best, best_score = round_best[1], round_best[2]
    report["changes"] = path
    report["best"] = best_score.summary(n)
    if best == current:
        report["reasons"].append("no change passed more of your eval questions than the version in use")
        return {**report, "version": None}
    again = await run("second run of the best", best)
    report["confirmed"] = again.summary(n)
    lost = sorted(base.passed - again.passed)
    if len(again.passed) <= len(base.passed) or lost:
        report["reasons"].append("the gain did not hold on a second run" + (f" (lost {', '.join(lost)})" if lost else ""))
    elif gate is not None:
        ok, detail = gate()
        if not ok:
            report["reasons"].append(f"regression checks failed: {detail}")
    report["accepted"] = not report["reasons"]
    reason = (f"{len(base.passed)}→{len(again.passed)}/{n} eval questions: " + "; ".join(path) if report["accepted"]
              else "rejected: " + "; ".join(report["reasons"]))
    version = store.add_version(component(specialist), best.to_dict(), report, reason, activate=report["accepted"])
    return {**report, "version": version["id"]}
