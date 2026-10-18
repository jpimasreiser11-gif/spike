"""Eval candidates (Evolution 4). A saved correction or a failure the user marked as fixed becomes a proposed eval
question; the user edits its checks and accepts or rejects it, and accepted ones are exported as JSONL and replayed
by `spike evolve check --replay`.

Checks are plain text rules, not a model's judgement: `include` strings must all appear in the answer, `exclude`
strings must not, and the run must finish without an error. The checks suggested for a correction come from the
numbers the user wrote (a negated one, "no del 18 %", must not appear); they are a starting point to edit, not a
measured truth.

Before a candidate can be accepted it is compared with SPIKE's own eval questions (the router set, evals/data in a
source checkout) and the candidates already accepted, so one question is not counted twice. Training data is not on
the user's computer and is not checked here; the training pipeline decontaminates its own data against eval sets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from spike.evolution.router_learning import LABELED
from spike.orchestrator.router import normalize

NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?:\s?%)?")
WORD = re.compile(r"[a-z0-9]+")
NEGATION = re.compile(r"(?:\b(?:no|not|ni|nunca|never|en vez|en lugar|instead|rather than)\b|\bno es\b)[^\d]{0,14}$")
OPENER = re.compile(r"^\s*(?:no|nope|not)\s*[,.!:;-]+", re.I)
PERCENT_SPACE = re.compile(r"(?<=\d)\s+(?=%)")
NGRAM = 3
TOO_CLOSE = 0.6  # share of a question's word trigrams found in one reference question
EVAL_DATA = Path(__file__).resolve().parents[2] / "evals" / "data"  # only in a source checkout


def suggested_checks(correction: str) -> dict[str, list[str]]:
    """Numbers the user wrote: the ones they negate ("no del 18 %", "not 18%") must not appear, the others must."""
    include: list[str] = []
    exclude: list[str] = []
    scan = OPENER.sub(lambda m: " " * len(m.group()), correction)  # "No, son 21 %": that "no" is not about 21
    for m in NUMBER.finditer(correction):
        n = re.sub(r"\s", "", m.group())
        target = exclude if NEGATION.search(normalize(scan[max(0, m.start() - 24):m.start()])) else include
        if n not in include and n not in exclude:
            target.append(n)
    return {"include": include[:5], "exclude": exclude[:5]}


def from_correction(item: dict[str, Any]) -> dict[str, Any]:
    return {"question": item["question"], "specialist": (item.get("specialists") or [None])[0],
            "reference": item["correction"], "rule": item.get("rule"),
            "checks": suggested_checks(item["correction"]),
            "from": "correction", "source": item["id"]}


def from_failure(item: dict[str, Any]) -> dict[str, Any]:
    return {"question": item["question"], "specialist": (item.get("specialists") or [None])[0],
            "reference": item.get("fix") or "", "checks": {"include": [], "exclude": []},
            "from": "failure", "source": item["id"]}


def _grams(text: str) -> set[tuple[str, ...]]:
    words = WORD.findall(normalize(text))
    if len(words) < NGRAM:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)}


def references(accepted: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(where it comes from, question) for every question a new candidate must not repeat."""
    refs = [("router set", json.loads(line)["query"]) for line in LABELED.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if EVAL_DATA.is_dir():
        for path in sorted(EVAL_DATA.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    refs.append((f"evals/data/{path.name}", str(row.get("prompt") or row.get("question") or "")))
    refs += [(f"accepted candidate {c['id']}", c["question"]) for c in accepted]
    return refs


def contamination(question: str, refs: list[tuple[str, str]]) -> dict[str, Any] | None:
    """The reference question closest to this one, when they share too much; None when it is new."""
    grams = _grams(question)
    if not grams:
        return None
    best = max(((len(grams & _grams(text)) / len(grams), where, text) for where, text in refs), default=None)
    if best is None or best[0] < TOO_CLOSE:
        return None
    return {"score": round(best[0], 2), "with": best[1], "text": best[2][:200]}


def _flat(text: str) -> str:
    """Lower case without accents, and "21 %" written like "21%" (Spanish puts a space before the sign)."""
    return PERCENT_SPACE.sub("", normalize(text))


def judge(text: str, error: str | None, checks: dict[str, list[str]]) -> tuple[bool, list[str]]:
    """Apply a candidate's checks to an answer: (passed, what failed)."""
    found = _flat(text)
    problems = [f"error: {error}"] if error else []
    problems += [f"missing '{s}'" for s in checks.get("include") or [] if _flat(s) not in found]
    problems += [f"contains '{s}'" for s in checks.get("exclude") or [] if _flat(s) in found]
    return not problems, problems


def export_jsonl(candidates: list[dict[str, Any]]) -> str:
    """Accepted candidates in the eval-data format (one JSON object per line, `id` and `prompt` first)."""
    return "".join(json.dumps({"id": c["id"], "prompt": c["question"], "specialist": c.get("specialist"),
                               "checks": c.get("checks") or {}, "reference": c.get("reference") or "",
                               "from": c.get("from"), "source": "spike-evolution"}, ensure_ascii=False) + "\n"
                   for c in candidates)
