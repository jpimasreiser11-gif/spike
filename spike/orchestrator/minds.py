"""Parallel Minds: one message, N independent answers (2 to 4), and the best of them chosen by SPIKE's own labels.

It runs only when a request asks for it (`parallel_minds` on the app's chat endpoint); `/v1`, MCP and the CLI have no
such parameter and never run it. Each mind is a complete run of the orchestrator (route, plan, specialists, checker),
so the time and the tokens are N times one run. The minds differ by temperature (a fixed spread, below) unless the
user picks a specialist or a provider for each. They may only use tools that read or compute (`read_only`): N copies
of a turn must not write N times, run code or place an order, and nobody is asked a question N times.

The pick is deterministic and uses what the trust labels already measure (spike/trust/claims.py), never a model:
an answer beats another by (1) answering at all, (2) a checker that did not fail, (3) more verified claims minus
unchecked ones, (4) fewer unchecked claims, (5) more verified claims, and last (6) the lower mind number. Hypotheses
count neither way. The model pass of the trust labels is not run on the minds (it would be N more calls).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from spike.agent.loop import Event
from spike.core.types import Message
from spike.orchestrator.orchestrator import Orchestrator, OrchestratorOptions, _merge

MIN_MINDS, MAX_MINDS = 2, 4
# the temperature of each mind when the user did not pick different specialists or providers: careful to loose, so
# the answers differ although the model and the prompt are the same (no seed is sent: providers sample at random)
TEMPERATURES = {2: (0.3, 0.9), 3: (0.3, 0.7, 1.0), 4: (0.2, 0.5, 0.8, 1.0)}
NO_COUNTS = {"verified": 0, "hypothesis": 0, "unchecked": 0}


@dataclass(frozen=True)
class Mind:
    index: int  # 0-based; shown as "Mind {index + 1}"
    mode: str | None = None  # a specialist id the user picked for it; None = the chat's
    provider_id: str | None = None  # a provider the user picked for it; None = the chat's
    temperature: float | None = None  # None = the user's setting

    def public(self) -> dict[str, Any]:
        return {"index": self.index, **{k: v for k, v in (("mode", self.mode), ("provider_id", self.provider_id),
                                                           ("temperature", self.temperature)) if v is not None}}


def plan_minds(n: int | None, picks: list[dict[str, Any]] | None = None) -> list[Mind]:
    """The minds a request asks for: `n` of them with spread temperatures, or one per entry of `picks` (each with an
    optional specialist `mode` and `provider_id`; a pick equal to an earlier one gets another temperature, so the
    answers still differ). ValueError when the number is outside 2 to 4 or `n` and `picks` disagree."""
    if picks is not None:
        if n is not None and n != len(picks):
            raise ValueError(f"'n' is {n} but {len(picks)} minds were picked")
        n = len(picks)
    if n is None or isinstance(n, bool) or not isinstance(n, int) or not MIN_MINDS <= n <= MAX_MINDS:
        raise ValueError(f"Parallel Minds runs {MIN_MINDS} to {MAX_MINDS} minds")
    ladder = TEMPERATURES[n]
    minds: list[Mind] = []
    for i in range(n):
        pick = (picks or [{}] * n)[i] or {}
        mode, provider_id = pick.get("mode") or None, pick.get("provider_id") or None
        mode = None if mode == "auto" else mode
        same = any((m.mode, m.provider_id) == (mode, provider_id) for m in minds)
        minds.append(Mind(i, mode, provider_id, ladder[i] if same or picks is None else None))
    return minds


@dataclass
class Candidate:
    """What one mind produced, as far as the choice needs it."""

    index: int
    text: str = ""
    error: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: dict(NO_COUNTS))
    verifier_failed: bool = False
    trust: Event | None = None  # the mind's `trust` event, as the orchestrator sent it
    private: bool = False
    finish_reason: str | None = None
    specialists: list[str] = field(default_factory=list)
    route: list[dict[str, Any]] = field(default_factory=list)  # who answered: name, provider and model of each
    elapsed_s: float = 0.0

    @property
    def answered(self) -> bool:
        return bool(self.text.strip()) and not self.error

    def key(self) -> tuple:
        """Bigger is better; the last item makes a tie go to the lower mind number."""
        c = self.counts
        return (self.answered, not self.verifier_failed, c["verified"] - c["unchecked"], -c["unchecked"],
                c["verified"], -self.index)

    def public(self) -> dict[str, Any]:
        return {"index": self.index, "ok": self.answered, "error": self.error, "counts": self.counts,
                "verifier_failed": self.verifier_failed, "elapsed_s": self.elapsed_s,
                "specialists": self.specialists, "route": self.route, "text": self.text,
                **({"trust": {k: v for k, v in self.trust.items() if k != "type"}} if self.trust else {})}


def pick(candidates: list[Candidate]) -> tuple[int | None, list[int], str]:
    """(the mind whose answer is shown or None when none answered, every mind best first, why): `none` (nobody
    answered), `only` (one answered), `labels` (the labels or the checker told them apart) or `order` (equal labels:
    the lower mind number)."""
    ranked = sorted(candidates, key=Candidate.key, reverse=True)
    order = [c.index for c in ranked]
    answered = [c for c in ranked if c.answered]
    if not answered:
        return None, order, "none"
    if len(answered) == 1:
        return answered[0].index, order, "only"
    return answered[0].index, order, "labels" if answered[0].key()[:-1] != answered[1].key()[:-1] else "order"


def mind_options(opts: OrchestratorOptions, mind: Mind) -> OrchestratorOptions:
    """The chat's options for one mind: its own temperature and specialist, claim labels on (the choice needs them,
    whatever the trust setting says), read-only tools, and no answer contract or Forge plan."""
    return replace(opts, mode=mind.mode or opts.mode,
                   temperature=opts.temperature if mind.temperature is None else mind.temperature,
                   trust=True, trust_model_pass=False, read_only=True, json_schema=None, forge=None,
                   checkpoints=None)


async def _one(mind: Mind, orchestrator: Orchestrator, history: list[Message], user_text: str,
               opts: OrchestratorOptions, cand: Candidate) -> AsyncIterator[Event]:
    """One mind's run: its events tagged with `mind`, then a `mind_result` summary. A run that raises is a mind that
    did not answer, not a failed chat."""
    tag = {"mind": mind.index}
    started = time.perf_counter()
    yield {"type": "mind_start", **tag}
    try:
        async for ev in orchestrator.run(history, user_text, mind_options(opts, mind)):
            if ev["type"] == "route":
                cand.route = [{k: v for k, v in s.items() if k in ("id", "name", "provider", "model")}
                              for s in ev.get("specialists") or []]
            elif ev["type"] == "trust":
                cand.trust = ev
                cand.counts = {**NO_COUNTS, **(ev.get("counts") or {})}
                cand.verifier_failed = bool(ev.get("verifier_failed"))
            elif ev["type"] == "done":
                cand.text, cand.error = ev["text"], ev.get("error")
                cand.private, cand.finish_reason = bool(ev.get("private")), ev.get("finish_reason")
                cand.specialists = list(ev.get("specialists") or [])
            yield {**ev, **tag}
    except Exception as exc:  # the other minds go on
        cand.error = f"{exc.__class__.__name__}: {exc}"
        yield {"type": "error", "message": cand.error, **tag}
    cand.elapsed_s = round(time.perf_counter() - started, 3)
    yield {"type": "mind_result", **tag, **cand.public()}


async def run_minds(minds: list[Mind], orchestrator_for: Callable[[Mind], Orchestrator], history: list[Message],
                    user_text: str, opts: OrchestratorOptions, concurrent: bool = False) -> AsyncIterator[Event]:
    """Run the minds (one after the other, or together when `concurrent`: a remote API) and stream their events,
    each tagged with `mind`. Then `minds_pick` and the chosen answer's own `trust` and `done` events, untagged, so
    the rest of the app handles it as the answer of an ordinary run."""
    started = time.perf_counter()
    candidates = [Candidate(m.index) for m in minds]
    yield {"type": "minds_start", "n": len(minds), "minds": [m.public() for m in minds]}
    runs = [_one(m, orchestrator_for(m), history, user_text, opts, c) for m, c in zip(minds, candidates, strict=True)]
    if concurrent:
        async for ev in _merge(runs):
            yield ev
    else:
        for run in runs:
            async for ev in run:
                yield ev
    chosen, order, why = pick(candidates)
    yield {"type": "minds_pick", "chosen": chosen, "ranking": order, "why": why,
           "minds": [{"index": c.index, "ok": c.answered, "counts": c.counts, "verifier_failed": c.verifier_failed}
                     for c in candidates]}
    winner = candidates[chosen] if chosen is not None else None
    if winner is not None and winner.trust is not None:
        yield winner.trust
    errors = [c.error for c in candidates if c.error]
    yield {"type": "done", "text": winner.text if winner else "",
           "error": None if winner else f"none of the {len(minds)} minds answered"
           + (f": {errors[0]}" if errors else ""),
           "finish_reason": winner.finish_reason if winner else None, "private": winner.private if winner else False,
           "specialists": winner.specialists if winner else [], "elapsed_s": round(time.perf_counter() - started, 3)}
