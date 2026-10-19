"""Answer extraction and statistics used by distillation filtering and evaluations."""

from __future__ import annotations

import math
import re
import unicodedata

_THINK = re.compile(r"(?s)<think>.*?</think>")


def strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


def extract_choice(text: str, n_options: int = 10) -> str | None:
    """Return the final option letter, trying in order: the last 'Answer: X' (markdown allowed, letters are
    upper case only so 'the answer is a ...' is not read as A), a last line that is only the letter
    ('**B**'), the last 'option is X' or 'Option: X', and the last standalone 'X.' or 'X)'."""
    letters = "ABCDEFGHIJ"[:n_options]
    body = strip_think(text)
    deco = r"[\s*_(\[]*"
    explicit = re.findall(rf"(?i:\banswer)(?:\s+(?i:is))?\s*[:：]?{deco}([{letters}])(?![A-Za-z])", body)
    if explicit:
        return explicit[-1]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if lines and (m := re.fullmatch(rf"{deco}([{letters}])[\s*_)\].:]*", lines[-1])):
        return m.group(1)
    stated = re.findall(rf"(?i:\b(?:option|choice))(?:\s+(?i:is)\s*[:：]?|\s*[:：]){deco}([{letters}])(?![A-Za-z])",
                        body)
    if stated:
        return stated[-1]
    loose = re.findall(rf"\b([{letters}])[\.\)]\s", body + " ")
    return loose[-1] if loose else None


def extract_yes_no(text: str) -> str | None:
    body = strip_think(text).lower()
    m = re.findall(r"answer\s*[:：]?[\s*_]*(yes|no|maybe)\b", body)
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


_FINAL = re.compile(r"(?i)\banswer\b[\s*_]*[:：][\s*_:：]*([^\n]*)")
_AMOUNT = re.compile(r"(?P<neg>[-−–]\s*)?\$?\s*(?P<neg2>[-−–]\s*)?"
                     r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)")
_PERCENT = re.compile(r"\)?\s*(?:%|per\s?cent)", re.I)
_SCALE_WORD = re.compile(r"(?<=[\d)])\s*(?:thousands?|millions?|billions?|percent)\s*$")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def extract_final(text: str) -> str | None:
    """The line after the last 'Answer:' (markdown allowed); without one, the last non-empty line."""
    body = strip_think(text)
    found = _FINAL.findall(body)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    line = found[-1] if found else (lines[-1] if lines else "")
    return line.strip(" \t*_`") or None


def parse_amount(text: str | None) -> tuple[float, bool] | None:
    """The first number of an answer line as (value, written as a percentage). Handles $, thousands commas,
    '-', the unicode minus and '(1,234)' as negative; scale words (million, ...) are ignored. After an '='
    only the part behind the last one is read, so 'Answer: 5829 - 5735 = 94' is 94."""
    if text is None:
        return None
    text = text.rsplit("=", 1)[-1]
    m = _AMOUNT.search(text)
    if not m:
        return None
    after = text[m.end():].lstrip()
    value = float(m["num"].replace(",", ""))
    bracketed = text[: m.start()].rstrip().endswith("(") and re.match(r"%?\s*\)", after) is not None
    return (-value if m["neg"] or m["neg2"] or bracketed else value), _PERCENT.match(after) is not None


def amount_matches(parsed: tuple[float, bool] | None, gold: float, rel_tol: float = 0.005) -> bool:
    """Within 0.5 % of the gold, or, when written as a percentage, its fraction (28 % for 0.28)."""
    if parsed is None:
        return False
    value, percent = parsed
    return numbers_match(value, gold, rel_tol) or (percent and numbers_match(value / 100, gold, rel_tol))


def normalize_span(text: str) -> str:
    """Lower case, articles, punctuation and a trailing scale word after a number removed, one space between
    words. Numbers keep their meaning: '16,284' is '16284' but '16.284' stays distinct, '(4,400)' is '-4400'."""
    text = unicodedata.normalize("NFKC", text).lower().replace("−", "-").strip()
    text = re.sub(r"\(\s*(\d[\d,.]*)\s*\)", r"-\1", _SCALE_WORD.sub("", text))
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = re.sub(r"[^\w\s.-]", "", re.sub(r"\b(?:a|an|the)\b", " ", text))
    return " ".join(t for t in (t if _NUMBER.fullmatch(t) else re.sub(r"\W", "", t) for t in text.split()) if t)


def span_set(text: str) -> set[str]:
    """The items of 'a; b; c' as a set of normalized spans (order does not matter)."""
    return {s for part in text.split(";") if (s := normalize_span(part))}


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
