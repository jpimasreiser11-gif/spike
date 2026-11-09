"""Answer extraction and statistics used by distillation filtering and evaluations."""

from __future__ import annotations

import math
import re
import unicodedata

_THINK = re.compile(r"(?s)<think>.*?</think>")


def strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


def extract_choice(text: str, n_options: int = 10) -> str | None:
    """Return the final option letter (upper case only, so 'the answer is a ...' is not read as A), trying in order:
    the last 'Answer: X' (markdown allowed; 'Answer: Option X', 'Answer Selection: X' and 'the correct answer is choice
    (X)' too); the last
    line that is only the letter ('**B**'), looked for through up to three short trailing note lines
    ('Confidence: moderate', a clinician disclaimer) that name no letter; the last 'option is X' or 'Option: X'; the
    last 'option X is (the) correct/right/best/answer', 'we select option X' or 'correct letter: X'; and the last
    standalone 'X.' or 'X)'. A verdict against a letter ('option X is wrong', 'Answer: Option X is not ...') never
    counts for the option rules, and letters beyond `n_options` are ignored."""
    letters = "ABCDEFGHIJ"[:n_options]
    body = strip_think(text)
    deco = r"[\s*_(\[]*"
    letter = rf"([{letters}])(?![A-Za-z])"
    opt = rf"(?i:option|choice)\b{deco}{letter}"
    against = r"(?!\s+(?i:is|are)(?i:n't|\s+(?:not|incorrect|wrong|false))\b)"
    # 'Answer: Option X' needs the ':' or 'is' first, so 'the answer choice B is wrong' is not read as B
    # 'Answer Selection: X' (M11) needs the ':' too, so 'the answer selection B is wrong' is not read as B
    explicit = re.finditer(rf"(?i:\banswer)[*_]*(?:(?:\s+(?i:is))?\s*[:：]?{deco}{letter}"
                           rf"|(?:\s+(?i:is)\s*[:：]?|\s*[:：]){deco}{opt}{against}"
                           rf"|\s+(?i:selection)[*_]*\s*[:：]{deco}(?:{opt}|{letter}){against})", body)
    if found := [m.group(m.lastindex) for m in explicit]:
        return found[-1]
    stated = rf"(?i:\b(?:option|choice))(?:\s+(?i:is)\s*[:：]?|\s*[:：]){deco}{letter}"
    # affirmative picks only ('option X is the answer', 'we select option X', 'correct letter: X'), never a verdict
    affirmed = (rf"(?i:\b(?:option|choice)){deco}{letter}[*_)\]]*\s+(?i:is)\s+(?i:the\s+)?"
                r"(?:(?i:answer)\b|(?i:correct|right|best)\b(?!\s+(?i:about|in|for|that|only|if|but|when|as)\b))"
                rf"|(?i:\b(?:we|i)\s+(?:(?:would|will|should|therefore|thus|then|now)\s+)*(?:select|choose|pick)\b)"
                rf"{deco}{opt}{against}"
                rf"|(?i:\bcorrect\s+letter)(?:\s+(?i:is))?\s*[:：]?{deco}{letter}{against}")
    loose = rf"\b([{letters}])[\.\)]\s"
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    for ln in reversed(lines[-4:]):
        if m := re.fullmatch(rf"{deco}([{letters}])[\s*_)\].:]*", ln):
            return m.group(1)
        if len(ln) > 300 or any(re.search(rule, ln + " ") for rule in (stated, affirmed, loose)):
            break
    if found := re.findall(stated, body):
        return found[-1]
    if found := [m.group(m.lastindex) for m in re.finditer(affirmed, body)]:
        return found[-1]
    found = re.findall(loose, body + " ")
    return found[-1] if found else None


_TEXT_CUE = re.compile(r"(?i:\b(?:(?:final|correct|best|right)\s+)?(?:answer|option|choice|diagnosis)"
                       r"(?:\s+selection)?(?:[*_]*\s+is\b|[*_]*\s*[:：]))[\s*_]*")
_CLAUSE_END = re.compile(r"\*\*|[.;,!?](?=\s|$)|\s+(?:because|as|since|which|given|due)\b|\s+[—–-]\s|\s\(")


def _plain(text: str) -> str:
    """Lower case without markdown emphasis or backticks, spaces collapsed, closing punctuation and quotes dropped."""
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans("", "", "*_`")).lower()
    return re.sub(r"\s+", " ", text).strip(" \"'“”‘’.,;:!?()[]")


def extract_option_text(text: str, options: list[str]) -> str | None:
    """The letter of the option whose whole text the answer states instead of its letter (M11: about a quarter of
    the base model's unparsed medicine answers), only when that text equals exactly one option: the last
    'the answer is <text>' / 'Answer: <text>' / 'the correct option is <text>' / 'the most likely diagnosis is <text>'
    (the rest of the line or its first clause), else a closing line that is only an option's text, looked for
    through up to three short trailing notes. Options that share a text, and one-letter options, are never read.
    Used only when extract_choice finds no letter."""
    letters: dict[str, set[str]] = {}
    for i, option in enumerate(options[:10]):
        key = _plain(option)
        if key and not (len(key) == 1 and key.isalpha()):
            letters.setdefault(key, set()).add("ABCDEFGHIJ"[i])
    picks = {key: next(iter(found)) for key, found in letters.items() if len(found) == 1}
    if not picks:
        return None
    body = strip_think(text)
    stated = None
    for m in _TEXT_CUE.finditer(body):
        rest = body[m.end():].split("\n", 1)[0]
        for candidate in (_plain(rest), _plain(_CLAUSE_END.split(rest, 1)[0])):
            if candidate in picks:
                stated = picks[candidate]
                break
    if stated:
        return stated
    named = set()
    for ln in reversed([ln.strip() for ln in body.splitlines() if ln.strip()][-4:]):
        if _plain(ln) in picks:
            named.add(picks[_plain(ln)])
        elif len(ln) > 300:
            break
    return named.pop() if len(named) == 1 else None


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
