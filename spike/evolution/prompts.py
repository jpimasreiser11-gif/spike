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


# ---------------------------------------------------------------- prompt regression (EV8)
# A candidate is a version of `prompt:<specialist>` that exists but is not in use: typed by the user (`propose`).
# It can become the version in use only after it is compared with the one in use on the local set: the user's
# accepted eval questions for the specialist that have checks (`eval_set`). That set holds the questions made from
# saved corrections (E1) and from fixed failures (E4); both are accepted candidates of the store and the report
# counts each kind. They are scored by `candidates.judge` (text that must or must not appear, and no error), without
# memory and at temperature 0, so the same version gets the same score. A candidate is blocked when its pass rate is
# more than TOLERANCE_POINTS below the one in use. The tolerance is in points of pass rate: with fewer than 50
# questions a single lost question is already more than 2 points, so on a small set nothing is lost for free, and on
# a large one a lone question of noise does not block a gain. Every verdict, passing or blocking, is written to the
# candidate's version (report and reason), so the history says why it is or is not in use.
TOLERANCE_POINTS = 2.0


def pending(store: EvolutionStore, specialist: str) -> list[dict[str, Any]]:
    """Candidate versions of this specialist that are not in use and not blocked; newest first."""
    return [v for v in store.versions(component(specialist))
            if v["report"].get("status") == "candidate" and not v["active"]]


def propose(store: EvolutionStore, specialist: str, lines: list[str] | None = None,
            skills: dict[str, str] | None = None) -> dict[str, Any]:
    """Store a candidate: the version in use plus these instruction lines and skill modes ("auto" drops a mode).
    Nothing changes what SPIKE does until `activate` passes it."""
    current = active(store, specialist)
    have = {normalize(x) for x in current.instructions}
    added: list[str] = []
    for line in (" ".join(str(x).split())[:MAX_LINE] for x in lines or []):
        if line and normalize(line) not in have:
            have.add(normalize(line))
            added.append(line)
    modes = current.skill_modes()
    for skill, mode in (skills or {}).items():
        if mode == "auto":
            modes.pop(skill, None)
        elif mode in SKILL_MODES:
            modes[skill] = mode
        else:
            raise ValueError(f"skill mode must be one of {', '.join((*SKILL_MODES, 'auto'))}, got '{mode}'")
    variant = Variant.of([*current.instructions, *added], modes)
    if len(variant.instructions) > MAX_INSTRUCTIONS:
        raise ValueError(f"a prompt can have at most {MAX_INSTRUCTIONS} learned lines")
    if variant == current:
        raise ValueError("nothing to change: the version in use already has these lines and skill modes")
    changes = [*(f"add: {x}" for x in added), *(f"skill {k}: {v}" for k, v in (skills or {}).items())]
    return store.add_version(component(specialist), variant.to_dict(),
                             {"status": "candidate", "source": "manual", "changes": changes},
                             "candidate: " + "; ".join(changes), activate=False)


class Scores:
    """Scores of versions on one question set, each computed once: a check compares several against the same one."""

    def __init__(self, questions: list[dict[str, Any]], answer: Answer):
        self.questions, self.answer = questions, answer
        self._done: dict[Variant, Score] = {}

    async def of(self, variant: Variant) -> Score:
        if variant not in self._done:
            self._done[variant] = await score(variant, self.questions, self.answer)
        return self._done[variant]


def unevaluated(n: int) -> dict[str, Any]:
    return {"questions": n, "evaluated": False, "ok": False, "tolerance_points": TOLERANCE_POINTS,
            "reason": f"only {n} accepted eval questions with checks for this specialist; accept at least "
                      f"{MIN_QUESTIONS} in Settings → Evolution to compare prompts"}


async def compare(scores: Scores, baseline: Variant, candidate: Variant,
                  tolerance: float = TOLERANCE_POINTS) -> dict[str, Any]:
    """Pass rates of two versions on the same questions, and whether the candidate stays within the tolerance."""
    n = len(scores.questions)
    if n < MIN_QUESTIONS:
        return unevaluated(n)
    origins: dict[str, int] = {}
    for q in scores.questions:
        origins[q.get("from") or "other"] = origins.get(q.get("from") or "other", 0) + 1
    base, cand = await scores.of(baseline), await scores.of(candidate)
    drop = round(100 * (len(base.passed) - len(cand.passed)) / n, 2)
    return {"questions": n, "origins": origins, "tolerance_points": tolerance, "baseline": base.summary(n),
            "candidate": cand.summary(n), "drop_points": drop, "lost": sorted(base.passed - cand.passed),
            "gained": sorted(cand.passed - base.passed), "evaluated": True, "ok": drop <= tolerance}


def verdict_text(report: dict[str, Any]) -> str:
    if not report.get("evaluated"):
        return report["reason"]
    return (f"{report['candidate']['passed']}/{report['questions']} eval questions against "
            f"{report['baseline']['passed']}/{report['questions']} for the version in use "
            f"({-report['drop_points'] + 0.0:+.1f} points, tolerance -{report['tolerance_points']:g})")


def record_verdict(store: EvolutionStore, version: dict[str, Any], report: dict[str, Any],
                   against: int | None, activated: bool = False) -> dict[str, Any]:
    """Write a candidate's comparison into its version: the report, the status and the reason, whatever the verdict."""
    status = "activated" if activated else "candidate" if report["ok"] else "blocked"
    reason = (f"activated after the check: {verdict_text(report)}" if activated else
              f"candidate checked: {verdict_text(report)}; can be activated" if status == "candidate" else
              f"blocked: {report.get('reason') or verdict_text(report)}")
    return store.annotate(version["id"], {"status": status, "regression": {**report, "against": against}}, reason)


async def check_candidate(store: EvolutionStore, specialist: str, version: dict[str, Any], scores: Scores,
                          tolerance: float = TOLERANCE_POINTS) -> dict[str, Any]:
    """Compare a candidate with the version in use and record the verdict in its version (nothing is activated)."""
    current = store.active(component(specialist))
    report = await compare(scores, active(store, specialist), Variant.from_dict(version["data"]), tolerance)
    record_verdict(store, version, report, current["id"] if current else None)
    return report


async def activate(store: EvolutionStore, specialist: str, version_id: int | None, answer: Answer,
                   gate: Callable[[], tuple[bool, str]] | None = None,
                   tolerance: float = TOLERANCE_POINTS) -> dict[str, Any]:
    """Use a candidate (the newest pending one when `version_id` is None) if it scores within the tolerance of the
    version in use and `gate` (the other regression checks) passes; otherwise it is blocked and nothing changes."""
    waiting = pending(store, specialist)
    version = store.version(version_id) if version_id is not None else waiting[0] if waiting else None
    if version is None or version["component"] != component(specialist):
        raise LookupError(f"no candidate prompt version for {specialist}"
                          + ("" if version_id is None else f" with id {version_id}"))
    if version["active"]:
        raise ValueError(f"v{version['id']} is already in use")
    current = store.active(component(specialist))
    report = await compare(Scores(eval_set(store, specialist), answer), active(store, specialist),
                           Variant.from_dict(version["data"]), tolerance)
    if report["ok"] and gate is not None:
        ok, detail = gate()
        if not ok:
            report = {**report, "ok": False, "reason": f"regression checks failed: {detail}"}
    record_verdict(store, version, report, current["id"] if current else None, activated=report["ok"])
    if report["ok"]:
        store.activate(version["id"])
    return {**report, "activated": report["ok"], "version": version["id"]}
