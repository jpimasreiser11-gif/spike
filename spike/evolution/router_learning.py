"""Router learning (Evolution 2). When the user retries an answer with another specialist, the question and the
specialist they picked teach the lexical router new keywords, kept as an overlay on the catalog's own keywords.
A new overlay is used only if it passes the gate, measured here and saved with it:

- the corrections it learned from are routed to the specialist the user picked more often than before;
- the dev split of the router set (spike/evolution/router_labeled.jsonl) gets no worse, first choice or exact set;
- the test split gets no worse either. Keywords are chosen on the corrections and the dev split only; the test split
  is read once, for the verdict, so it stays a fair check of what was not tuned on.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from spike.orchestrator.router import LexicalRouter, _pattern, normalize
from spike.specialists.catalog import Catalog

LABELED = Path(__file__).with_name("router_labeled.jsonl")
WORD = re.compile(r"[a-z0-9]+")
MAX_KEYWORDS_PER_QUESTION = 2
MAX_WEIGHT = 3.0
# Words that say nothing about a domain, in the languages the router set uses (normalized: no accents)
_STOP_WORDS = """
para pero porque como cual cuales cuando donde quien quienes este esta estos estas ese esa esos esas aquel aquella
tengo tiene tienen tener hace hacer hago puedo puede pueden quiero quieres necesito favor gracias hola sobre entre
desde hasta tambien todo todos toda todas otro otra otros otras mismo misma algo alguien nada mucho muchos poco
mejor peor bien cosa cosas manera forma ahora antes despues siempre nunca solo sola explica explicame dime dame
ayudame ayuda escribe hazme cuanto cuanta cuantos cuantas debo deberia seria esto cada vez veces ayer manana
semana semanas dias meses anos hora horas minuto minutos tarde noche
what which when where who whom whose why how this that these those there their them they then than with without
from into onto about above below after before could would should will shall have has had having does doing done
make made give tell write explain please help need want know some more most much many very just also only even
your yours mine ours here each every other another such same between through over under again today
yesterday tomorrow week weeks days month months year years hour hours minute minutes time times
"""
STOP = set(_STOP_WORDS.split())


def load_labeled(split: str | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in LABELED.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def evaluate(catalog: Catalog, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """First-choice and exact-set accuracy of the lexical router on labelled rows ({query, labels})."""
    router = LexicalRouter(catalog)
    primary = exact = 0
    for r in rows:
        got = router.route(r["query"]).specialists
        primary += got[0] in r["labels"]
        exact += set(got) == set(r["labels"])
    n = len(rows)
    return {"n": n, "primary": round(primary / n, 4) if n else None, "exact": round(exact / n, 4) if n else None}


def apply_overlay(catalog: Catalog, overlay: dict[str, dict[str, float]]) -> Catalog:
    """A copy of the catalog with the learned keywords added (a learned weight adds to a catalog keyword's)."""
    out = copy.deepcopy(catalog)
    for sid, words in (overlay or {}).items():
        spec = out.specialists.get(sid)
        if spec is None:
            continue  # a custom specialist that was removed
        for word, weight in words.items():
            spec.keywords[word] = spec.keywords.get(word, 0.0) + float(weight)
    return out


def _words(text: str) -> set[str]:
    return {w for w in WORD.findall(normalize(text)) if len(w) >= 4 and w not in STOP and not w.isdigit()}


def _known(catalog: Catalog, sid: str, word: str) -> bool:
    return any(_pattern(k).search(word) for k in catalog.specialists[sid].keywords)


def corrections_rows(corrections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The user's latest pick for each question, as labelled rows."""
    latest: dict[str, dict[str, Any]] = {}
    for c in sorted(corrections, key=lambda c: c.get("created", 0)):
        latest[normalize(c["query"]).strip()] = {"query": c["query"], "labels": [c["specialist"]]}
    return list(latest.values())


def learn_overlay(base: Catalog, corrections: list[dict[str, Any]],
                  dev: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Keywords that send each corrected question to the specialist the user picked: words of the question that no
    other specialist's corrections or dev questions use, weighted just enough to win, kept only if dev does not drop."""
    rows = [r for r in corrections_rows(corrections) if r["labels"][0] in base.specialists]
    used_by: dict[str, set[str]] = {}
    for r in rows + dev:
        for w in _words(r["query"]):
            used_by.setdefault(w, set()).update(r["labels"])
    target_count: dict[tuple[str, str], int] = {}
    for r in rows:
        for w in _words(r["query"]):
            target_count[(r["labels"][0], w)] = target_count.get((r["labels"][0], w), 0) + 1
    dev_base = evaluate(base, dev)
    overlay: dict[str, dict[str, float]] = {}
    for r in rows:
        sid = r["labels"][0]
        catalog = apply_overlay(base, overlay)
        router = LexicalRouter(catalog)
        if router.route(r["query"]).specialists[0] == sid:
            continue
        words = sorted((w for w in _words(r["query"]) if used_by.get(w) == {sid} and not _known(catalog, sid, w)),
                       key=lambda w: (-target_count[(sid, w)], -len(w), w))[:MAX_KEYWORDS_PER_QUESTION]
        if not words:
            continue
        scores = router.score(r["query"])
        rival = max((s for k, s in scores.items() if k != sid), default=0.0)
        needed = max(router.threshold, rival + 0.5) - scores.get(sid, 0.0)
        weight = min(MAX_WEIGHT, max(1.0, round(needed / len(words) * 2 + 0.49) / 2))  # rounded up to 0.5
        trial = copy.deepcopy(overlay)
        for w in words:
            trial.setdefault(sid, {})[w] = max(trial.get(sid, {}).get(w, 0.0), weight)
        dev_trial = evaluate(apply_overlay(base, trial), dev)
        if dev_trial["primary"] >= dev_base["primary"] and dev_trial["exact"] >= dev_base["exact"]:
            overlay = trial
    return overlay


def gate(base: Catalog, overlay: dict[str, dict[str, float]], corrections: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure the overlay against the catalog alone; `accepted` only if the corrections improve and neither split
    of the router set gets worse."""
    rows = corrections_rows(corrections)
    learned = apply_overlay(base, overlay)
    report: dict[str, Any] = {"before": {}, "after": {}}
    for name, data in (("corrections", rows), ("dev", load_labeled("dev")), ("test", load_labeled("test"))):
        report["before"][name], report["after"][name] = evaluate(base, data), evaluate(learned, data)
    b, a = report["before"], report["after"]
    reasons = []
    if not overlay:
        reasons.append("no new keyword would route the corrected questions without hurting the dev split")
    elif not rows or a["corrections"]["primary"] <= b["corrections"]["primary"]:
        reasons.append("the corrections are not routed better")
    for split in ("dev", "test"):
        for metric in ("primary", "exact"):
            if a[split][metric] < b[split][metric]:
                reasons.append(f"{split} {metric} drops from {b[split][metric]:.2f} to {a[split][metric]:.2f}")
    report["accepted"] = not reasons
    report["reasons"] = reasons
    report["keywords"] = sum(len(v) for v in overlay.values())
    return report
