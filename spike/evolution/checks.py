"""The regression gate (Evolution 5): `spike evolve check` and Settings → Evolution run the same checks.

- router: the built-in router keeps its floor on the router set, and a learned overlay is no worse than it;
- catalog: the catalog and custom specialists load, and every tool they list exists;
- skills: every installed skill is valid;
- adapters: each installed adapter version is the file that was accepted (same SHA-256);
- strategy: skill routing on the labelled requests is no worse with the learned tie-break applied (EV3);
- prompts (optional, runs the model): each specialist's learned prompt scores no lower than the built-in one, and each
  pending candidate prompt no lower than the one in use, on the local eval set, within `prompts.TOLERANCE_POINTS`
  (EV8); a candidate that fails is blocked and the verdict is written to its version;
- replay (optional, runs the model): accepted eval candidates are answered again and their checks applied.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from spike.evolution import candidates as cand
from spike.evolution import prompts, strategy
from spike.evolution.adapters import sha256
from spike.evolution.router_learning import apply_overlay, evaluate, load_labeled
from spike.specialists.catalog import load_catalog
from spike.tools.base import HeadlessBroker

FLOOR = {"dev": 0.85, "test": 0.6}  # the same floors as tests/test_core.py
Answer = Callable[[dict[str, Any]], Awaitable[tuple[str, str | None]]]


def _check(name: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, **extra}


def router_check(state) -> dict[str, Any]:
    base = state.base_catalog()
    built_in = {s: evaluate(base, load_labeled(s)) for s in ("dev", "test")}
    problems = [f"built-in {s} first choice {built_in[s]['primary']:.2f} < {FLOOR[s]}"
                for s in FLOOR if built_in[s]["primary"] < FLOOR[s]]
    overlay = state.evolution.router_overlay()
    current = {s: evaluate(apply_overlay(base, overlay), load_labeled(s)) for s in ("dev", "test")} if overlay else None
    for s, numbers in (current or {}).items():
        problems += [f"learned {s} {m} {numbers[m]:.2f} < built-in {built_in[s][m]:.2f}"
                     for m in ("primary", "exact") if numbers[m] < built_in[s][m]]
    shown = current or built_in
    detail = "; ".join(problems) or (f"{'learned' if overlay else 'built-in'}: dev {shown['dev']['primary']:.2f}, "
                                     f"test {shown['test']['primary']:.2f} first choice")
    return _check("router", not problems, detail, built_in=built_in, current=current)


def catalog_check(state) -> dict[str, Any]:
    try:
        catalog = load_catalog(extra=state.store.get_setting("custom_specialists", []))
    except (KeyError, ValueError, TypeError) as exc:
        return _check("catalog", False, f"does not load: {exc}")
    names = set(state.tools.names())
    missing = [f"{s.id}: {t}" for s in catalog.specialists.values() for t in s.tools if t not in names]
    return _check("catalog", not missing, f"unknown tools: {', '.join(missing)}" if missing else
                  f"{len(catalog.specialists)} specialists, every tool exists", count=len(catalog.specialists))


def skills_check(state) -> dict[str, Any]:
    state.skills.reload()
    errors = list(state.skills.errors)
    return _check("skills", not errors, "; ".join(errors) or f"{len(state.skills.all())} skills valid",
                  count=len(state.skills.all()))


def adapters_check(state) -> dict[str, Any]:
    problems, count = [], 0
    for spec in state.catalog.specialists.values():
        active = state.evolution.store.active(f"adapter:{spec.id}") if spec.adapter else None
        if active is None:
            continue
        count += 1
        dest = state.adapters_path() / f"{spec.adapter}.gguf"
        if not dest.is_file():
            problems.append(f"{spec.id}: {dest.name} is missing")
        elif sha256(dest) != active["data"]["sha256"]:
            problems.append(f"{spec.id}: {dest.name} is not the accepted file (checksum differs)")
    return _check("adapters", not problems, "; ".join(problems) or
                  (f"{count} installed adapters match their accepted files" if count else "no versioned adapters"),
                  count=count)


def strategy_check(state) -> dict[str, Any]:
    """The tie-break in use (EV3) must not make skill routing worse than the router's own order."""
    preference = state.evolution.strategy_preference()
    uses = state.evolution.store.count_runs()
    if preference is None:
        return _check("strategy", True, f"no learned tie-break in use ({uses} recorded uses)", uses=uses)
    routing = strategy.compare_routing(state.skills, preference)
    b, a = routing["before"], routing["after"]
    detail = (f"skill routing {b['correct']}/{b['n']} -> {a['correct']}/{a['n']} with the learned tie-break"
              + ("" if routing["ok"] else f"; now wrong: {'; '.join(a['wrong'])}"))
    return _check("strategy", routing["ok"], detail, uses=uses, before=b["correct"], after=a["correct"], n=b["n"])


async def prompts_check(state, answer: prompts.Answer | None = None) -> dict[str, Any]:
    """EV8: for each specialist with a learned prompt or a pending candidate, score the versions on its accepted eval
    questions. The version in use must not score lower than the built-in prompt, nor a candidate lower than the
    version in use, beyond the tolerance; a candidate that does is blocked (its version says why)."""
    store = state.evolution.store
    results: list[dict[str, Any]] = []
    for spec in state.catalog.specialists:
        waiting, current = prompts.pending(store, spec), store.active(prompts.component(spec))
        if not waiting and current is None:
            continue
        scores = prompts.Scores(prompts.eval_set(store, spec),
                                answer or (lambda q, v, spec=spec: answer_with_variant(state, q, spec, v)))
        if current is not None:
            report = await prompts.compare(scores, prompts.Variant(), prompts.Variant.from_dict(current["data"]))
            results.append({"specialist": spec, "what": "in use", "version": current["id"], **report})
        for version in reversed(waiting):
            report = await prompts.check_candidate(store, spec, version, scores)
            results.append({"specialist": spec, "what": "candidate", "version": version["id"], **report})
    bad = [r for r in results if not r["ok"]]
    detail = ("no learned or candidate prompt versions to compare" if not results else
              "; ".join(f"{r['specialist']} {r['what']} v{r['version']}: {prompts.verdict_text(r)}" for r in bad)
              or f"{len(results)} prompt versions within {prompts.TOLERANCE_POINTS:g} points of what they are compared with")
    return _check("prompts", not bad, detail, results=results)


async def answer_with_spike(state, candidate: dict[str, Any]) -> tuple[str, str | None]:
    """Ask SPIKE the question as a new chat would (memory included, no one to approve tools)."""
    await state.ensure_adapters()
    orchestrator = state.orchestrator(broker=HeadlessBroker(state.broker))
    mode = candidate.get("specialist") if candidate.get("specialist") in state.catalog.specialists else "auto"
    options = state.options(mode)
    if state.memory_settings()["enabled"]:
        options.memory = await state.memory.recall(candidate["question"], None)
    text, error = "", None
    async for ev in orchestrator.run([], candidate["question"], options):
        if ev["type"] == "done":
            text, error = ev["text"], ev.get("error")
    return text, error


async def answer_with_variant(state, candidate: dict[str, Any], specialist: str, variant) -> tuple[str, str | None]:
    """Ask one specialist with a learned-prompt variant in place of the active one: no memory (the gain must be the
    prompt's own), temperature 0 (the same question gets the same answer), no one to approve tools."""
    await state.ensure_adapters()
    orchestrator = state.orchestrator(broker=HeadlessBroker(state.broker))
    options = state.options(specialist)
    options.learned_instructions = {**options.learned_instructions, specialist: list(variant.instructions)}
    options.learned_skills = {**options.learned_skills, specialist: variant.skill_modes()}
    options.temperature = 0.0
    text, error = "", None
    async for ev in orchestrator.run([], candidate["question"], options):
        if ev["type"] == "done":
            text, error = ev["text"], ev.get("error")
    return text, error


async def replay_check(state, answer: Answer | None = None) -> dict[str, Any]:
    accepted = list(reversed(state.evolution.store.items("candidate", "accepted")))
    if not accepted:
        return _check("replay", True, "no accepted eval candidates", results=[], passed=0, total=0)
    results = []
    for c in accepted:
        try:
            text, error = await (answer or (lambda c: answer_with_spike(state, c)))(c)
        except Exception as exc:  # one broken question must not stop the others
            text, error = "", f"{exc.__class__.__name__}: {exc}"
        passed, problems = cand.judge(text, error, c.get("checks") or {})
        results.append({"id": c["id"], "question": c["question"][:200], "passed": passed, "problems": problems,
                        "checked": bool((c.get("checks") or {}).get("include") or (c.get("checks") or {}).get("exclude"))})
    failed = [r for r in results if not r["passed"]]
    return _check("replay", not failed, f"{len(results) - len(failed)}/{len(results)} candidates pass their checks",
                  results=results, passed=len(results) - len(failed), total=len(results))


async def run_checks(state, replay: bool = False, answer: Answer | None = None, prompt_versions: bool = False,
                     prompt_answer: prompts.Answer | None = None) -> dict[str, Any]:
    checks = [router_check(state), catalog_check(state), skills_check(state), adapters_check(state),
              strategy_check(state)]
    if prompt_versions:
        checks.append(await prompts_check(state, prompt_answer))
    if replay:
        checks.append(await replay_check(state, answer))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}

