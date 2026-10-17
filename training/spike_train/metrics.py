"""Answer extraction and statistics used by distillation filtering and evaluations."""

from __future__ import annotations

import math
import re

_THINK = re.compile(r"(?s)<think>.*?</think>")


def strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


def extract_choice(text: str, n_options: int = 10) -> str | None:
    """Return the final option letter. Prefers an explicit 'Answer: X' line, else the last standalone letter."""
    letters = "ABCDEFGHIJ"[:n_options]
    body = strip_think(text)
    explicit = re.findall(rf"(?i)answer\s*(?:is)?\s*[:：]?\s*\(?\**([{letters}])\b", body)
    if explicit:
        return explicit[-1].upper()
    loose = re.findall(rf"\b([{letters}])[\.\)]\s", body + " ")
    return loose[-1].upper() if loose else None


def extract_yes_no(text: str) -> str | None:
    body = strip_think(text).lower()
    m = re.findall(r"answer\s*[:：]?\s*\**(yes|no|maybe)\b", body)
    if m:
        return m[-1]
    m = re.findall(r"\b(yes|no|maybe)\b", body)
    return m[-1] if m else None


def extract_number(text: str) -> float | None:
    """Final numeric answer: an explicit 'Answer: N' (or GSM8K '#### N') wins, else the last number in the text."""
    body = strip_think(text).replace(",", "").replace("$", "")
    explicit = re.findall(r"(?i)(?:answer\s*(?:is)?\s*[:：]?|####)\s*\**\s*(-?\d+(?:\.\d+)?)", body)
    nums = explicit or re.findall(r"-?\d+(?:\.\d+)?", body)
    return float(nums[-1]) if nums else None


def numbers_match(value: float | None, target: float, rel_tol: float = 1e-4) -> bool:
    return value is not None and abs(value - target) <= max(1e-6, abs(target) * rel_tol)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value. b = only variant A correct, c = only variant B correct."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)
