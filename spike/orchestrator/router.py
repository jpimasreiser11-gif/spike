"""Stage-1 router: fast, deterministic, zero-cost lexical scoring of a request against each specialist.

It decides most requests without any model call. Ambiguous or multi-domain requests are escalated to the
LLM planner (planner.py). Accuracy is measured on spike/evolution/router_labeled.jsonl (tests/test_core.py; the
test split also guards router learning, spike/evolution/router_learning.py).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from spike.specialists.catalog import Catalog


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(normalize(keyword)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\w]){escaped}(?![\w])")


@dataclass
class RouteDecision:
    mode: str  # "direct" (core only) | "single" | "multi"
    specialists: list[str]
    scores: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    ambiguous: bool = False
    method: str = "lexical"


class LexicalRouter:
    def __init__(self, catalog: Catalog, threshold: float = 3.0, multi_ratio: float = 0.6, max_specialists: int = 3):
        self.catalog = catalog
        self.threshold = threshold
        self.multi_ratio = multi_ratio
        self.max_specialists = max_specialists

    def score(self, text: str) -> dict[str, float]:
        norm = normalize(text)
        scores: dict[str, float] = {}
        for spec in self.catalog.specialists.values():
            total = 0.0
            for keyword, weight in spec.keywords.items():
                hits = len(_pattern(keyword).findall(norm))
                if hits:
                    total += weight * min(hits, 2)
            if total:
                scores[spec.id] = total
        return scores

    def route(self, text: str) -> RouteDecision:
        scores = self.score(text)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked or ranked[0][1] < self.threshold:
            return RouteDecision(mode="direct", specialists=["core"], scores=scores, confidence=0.5, ambiguous=bool(ranked))
        top = ranked[0][1]
        chosen = [sid for sid, s in ranked if s >= max(self.threshold, top * self.multi_ratio)][: self.max_specialists]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = round(top / (top + second + 1.0), 3)
        if len(chosen) == 1:
            return RouteDecision(mode="single", specialists=chosen, scores=scores, confidence=confidence,
                                 ambiguous=confidence < 0.55)
        return RouteDecision(mode="multi", specialists=chosen, scores=scores, confidence=confidence, ambiguous=True)
