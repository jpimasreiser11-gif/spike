"""Deterministic text matching for the trust checks: spelling-independent words, numbers, names, quoted fragments and
the support a passage gives a claim. No model is involved. The thresholds are fixed engineering choices, not values
tuned on data (see docs/ARCHITECTURE.md, "Trustworthy answers")."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import cached_property

from spike.skills.engine import STOPWORDS

FRAGMENT_MIN = 0.85  # difflib ratio of the two texts' words: a quoted fragment this close to the source was found
SUPPORT_MIN = 0.5  # share of the claim's content words the passage has
ANCHORED_MIN = 0.8  # without a number or name to check, the passage must have this share to back a claim
WINDOW = 60  # words of a long source compared with a claim; a source this short or shorter is read whole
WHOLE_SOURCE = 150
CANDIDATES = 40  # positions tried per rare word when looking for the passage that matches a claim

QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'", "‚": "'",
                        "‹": "'", "›": "'", "—": "-", "–": "-", "−": "-", "‐": "-", "‑": "-"})
EXTRA_STOP = {  # words of citation cues and connectives that carry no claim
    "segun", "acuerdo", "conforme", "according", "stated", "described", "indica", "dice", "afirma", "menciona",
    "senala", "recoge", "establece", "explica", "contiene", "figura", "consta", "aparece", "says", "states",
    "mentions", "shows", "indicates", "reports", "lists", "contains", "tiene", "tienen", "hay", "han", "son", "fue",
    "fueron", "ser", "era", "lo", "le", "les", "o", "u", "mas", "pero", "esto", "eso", "estos", "estas", "ese",
    "esa", "unos", "unas", "also", "but", "can", "will", "not", "than", "then", "that", "these", "those", "was",
    "were", "has", "have", "had", "its", "into", "each", "per", "via"}
TOKEN = re.compile(r"[^\W_]+")
MARKDOWN = re.compile(r"[*_`~]+")
SPACE_THOUSANDS = re.compile(r"(?<=\d)[   ](?=\d{3}(?!\d))")  # 1 200 with a no-break space
NUMBER = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?(?!\w)")
URL = re.compile(r"https?://[^\s)\]>\"'«»“”]+[^\s)\]>\"'«»“”.,;:!?]")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
FILENAME = re.compile(r"(?<![\w/.-])(?:[\w-]+/)*[\w-]+(?:\.[\w-]+)*\.(?:md|txt|py|js|ts|tsx|json|jsonl|csv|tsv|pdf|docx|"
                      r"xlsx|pptx|html?|css|ya?ml|toml|sql|xml|svg|png|jpe?g|gif|log|ini|cfg|sh)\b", re.I)
NAME_TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][\w'’-]*")
SENTENCE_END = (".", "!", "?", "…", ":", ";", "¿", "¡", "(", '"', "«", "“", "-", "•", ">", "#", "|", "[")
ELLIPSIS = re.compile(r"\.{3}|…|\[\s*(?:\.{3}|…)\s*\]")


def fold(text: str) -> str:
    """Lower case, without accents, typographic quotes and dashes plain, markdown marks gone, one space between
    words: what two spellings of a text share."""
    text = SPACE_THOUSANDS.sub("", text)
    text = unicodedata.normalize("NFKC", text).translate(QUOTES)
    text = unicodedata.normalize("NFD", MARKDOWN.sub(" ", text))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


STOP = {fold(w) for w in STOPWORDS} | EXTRA_STOP


def words(text: str) -> list[str]:
    return TOKEN.findall(fold(text))


def stem(word: str) -> str:
    """A word without its plural: 'cliente' and 'clientes', 'ciudad' and 'ciudades', 'file' and 'files' agree."""
    if len(word) > 3 and word.endswith("s"):
        word = word[:-1]
    return word[:-1] if len(word) > 4 and word.endswith("e") else word


def content_words(text: str) -> list[str]:
    """The words that carry the meaning, once each, in order of appearance."""
    out = [stem(w) for w in words(text) if w not in STOP and (len(w) > 1 or w.isdigit())]
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------------------------ numbers
def _canon(int_part: str, frac: str = "") -> str:
    int_part = int_part.lstrip("0") or "0"
    frac = frac.rstrip("0")
    return f"{int_part}.{frac}" if frac else int_part


def number_values(raw: str) -> frozenset[str]:
    """What a written number can mean: '1.200' is 1200 or 1.2 (the dot may be a thousands mark or a decimal
    point), '1.234,5' and '1,234.5' are 1234.5, '12,5' is 12.5. Two spellings are the same number when they share
    a reading."""
    marks = [c for c in raw if c in ".,"]
    if not marks:
        return frozenset({_canon(raw)})
    last = max(raw.rfind("."), raw.rfind(","))
    head, frac = raw[:last], raw[last + 1:]
    digits = head.replace(".", "").replace(",", "")
    if len(marks) > 1 and len(set(marks)) == 1:  # 1.234.567: only thousands marks
        return frozenset({_canon(digits + frac)})
    if len(set(marks)) > 1:  # 1.234,5: the last mark is the decimal one
        return frozenset({_canon(digits, frac)})
    if len(frac) == 3 and 1 <= len(head) <= 3 and head != "0":  # 1.200: a thousands mark or a decimal point
        return frozenset({_canon(digits + frac), _canon(digits, frac)})
    return frozenset({_canon(digits, frac)})


@dataclass(frozen=True)
class Number:
    raw: str
    values: frozenset[str]


def numbers(text: str) -> list[Number]:
    """The numbers written in a text, with every value each can mean. A date or a time gives its parts."""
    plain = URL.sub(" ", fold(text))
    return [Number(m.group(), number_values(m.group())) for m in NUMBER.finditer(plain)]


def number_set(text: str) -> frozenset[str]:
    return frozenset(v for n in numbers(text) for v in n.values)


# ------------------------------------------------------------------------------------------------ names
def names(text: str, acronyms: bool = True) -> list[str]:
    """What a claim names and a passage must have too: URLs, e-mails, file names, acronyms (IVA, unless `acronyms`
    is off), identifiers with digits (ZX-ALBATROS-9931) and capitalised words that do not start a sentence. Case and
    accents do not matter when they are compared."""
    text = MARKDOWN.sub(" ", text)
    found: list[str] = []
    for pattern in (URL, EMAIL, FILENAME):
        found += [m.group() for m in pattern.finditer(text)]
        text = pattern.sub(" ", text)
    for m in NAME_TOKEN.finditer(text):
        token = m.group().strip("'’-")
        before = text[:m.start()].rstrip()
        starts = not before or before.endswith(SENTENCE_END)
        if len(token) < 2 or token.isdigit():
            continue
        has_digit, has_alpha = any(c.isdigit() for c in token), any(c.isalpha() for c in token)
        acronym = acronyms and token.upper() == token and sum(c.isalpha() for c in token) >= 2
        capitalised = token[0].isupper() and token[1:].islower() and not starts and fold(token) not in STOP
        if (has_digit and has_alpha) or acronym or capitalised:
            found.append(token)
    return list(dict.fromkeys(found))


# ------------------------------------------------------------------------------------------------ documents
class Doc:
    """A text prepared for matching: its words in order with where each one is, an index from word to positions,
    and every number it has."""

    def __init__(self, text: str):
        self.text = text
        self.folded = fold(text)
        self.spans = [(m.start(), m.end()) for m in TOKEN.finditer(self.folded)]
        self.words = [self.folded[a:b] for a, b in self.spans]
        self.canon = " " + " ".join(self.words) + " "
        self.offsets, at = [], 1
        for w in self.words:
            self.offsets.append(at)
            at += len(w) + 1
        shown = [(m.start(), m.end()) for m in TOKEN.finditer(text)]
        self.shown_spans = shown if len(shown) == len(self.spans) else None  # the words as the source wrote them

    @cached_property
    def stems(self) -> list[str]:
        return [stem(w) for w in self.words]

    @cached_property
    def index(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for i, s in enumerate(self.stems):
            out.setdefault(s, []).append(i)
        return out

    def slice(self, a: int, b: int) -> str:
        """The folded text of words a..b (b excluded)."""
        a, b = max(0, a), min(len(self.words), b)
        return self.folded[self.spans[a][0]:self.spans[b - 1][1]] if a < b else ""

    def shown(self, a: int, b: int) -> str:
        """Words a..b as the source wrote them (folded if the two cannot be lined up), for showing to the user."""
        a, b = max(0, a), min(len(self.words), b)
        if self.shown_spans is None or a >= b:
            return self.slice(a, b)
        return " ".join(self.text[self.shown_spans[a][0]:self.shown_spans[b - 1][1]].split())


@dataclass
class Support:
    """How much of a claim a passage has. `score` is the share of the claim's content words the passage has; it is
    0.0 when the claim has a number or a name the passage lacks (`missing`), because a changed figure or a wrong
    name is what an invented citation looks like. `anchors` counts the numbers and names the passage does have."""

    score: float
    overlap: float
    missing: list[str] = field(default_factory=list)
    anchors: int = 0

    @property
    def ok(self) -> bool:
        return self.score >= SUPPORT_MIN and not self.missing

    @property
    def backs(self) -> bool:
        """Enough to call a claim backed when the passage is all there is to go on."""
        return self.ok and (self.anchors > 0 or self.overlap >= ANCHORED_MIN)


def _has_name(name: str, passage: str, pstems: set[str]) -> bool:
    folded = fold(name)
    if folded.startswith("http") or "@" in folded:  # a URL or an e-mail address: as written
        return folded.rstrip("/") in passage
    if "." in folded or "/" in folded:  # a file name: with its folder, or alone
        return folded in passage or folded.rsplit("/", 1)[-1] in passage
    parts = [stem(w) for w in TOKEN.findall(folded)]
    return bool(parts) and all(p in pstems for p in parts)


def support(claim: str, passage: str, acronyms: bool = True) -> Support:
    """The support `passage` gives `claim`: token overlap, with every number and name of the claim required. A tool's
    output has numbers but rarely the labels the claim puts on them, so for it `acronyms` is off ('IVA' need not
    be printed; 'Norte' or 'ZX-9931' still must be)."""
    wanted = content_words(claim)
    folded = fold(passage)
    pstems = {stem(w) for w in TOKEN.findall(folded)}
    overlap = sum(1 for w in wanted if w in pstems) / len(wanted) if wanted else 0.0
    have = number_set(passage)
    missing, anchors = [], 0
    for n in numbers(claim):
        if n.values & have:
            anchors += 1
        else:
            missing.append(n.raw)
    for name in names(claim, acronyms):
        if _has_name(name, folded, pstems):
            anchors += 1
        else:
            missing.append(name)
    overlap = round(overlap, 3)
    return Support(score=0.0 if missing else overlap, overlap=overlap, missing=missing, anchors=anchors)


# ------------------------------------------------------------------------------------------------ fragments
@dataclass
class Found:
    ratio: float  # 1.0: word for word
    start: int  # words of the source where the fragment is
    end: int

    @property
    def ok(self) -> bool:
        return self.ratio >= FRAGMENT_MIN


def _locate(piece: str, doc: Doc) -> Found | None:
    """Where one uninterrupted piece of a quote is in the source: word for word, or the closest stretch."""
    qw = words(piece)
    if not qw:
        return None
    exact = doc.canon.find(" " + " ".join(qw) + " ")
    if exact >= 0:
        start = bisect_left(doc.offsets, exact + 1)
        return Found(1.0, start, start + len(qw))
    qstems = [stem(w) for w in qw]
    anchors = sorted((len(doc.index[s]), j) for j, s in enumerate(qstems) if s in doc.index and s not in STOP)[:3]
    best, text, tried = None, " ".join(qw), set()
    for _, j in anchors:
        for pos in doc.index[qstems[j]][:CANDIDATES]:
            for size in (len(qw), len(qw) - 1, len(qw) + 1):
                start = pos - j
                if size < 1 or start < 0 or (start, size) in tried:
                    continue
                tried.add((start, size))
                window = " ".join(doc.words[start:start + size])
                ratio = SequenceMatcher(None, text, window, autojunk=False).ratio() if window else 0.0
                if best is None or ratio > best.ratio:
                    best = Found(round(ratio, 3), start, min(len(doc.words), start + size))
    if best is not None and best.ratio < 1.0 and support(piece, doc.slice(best.start, best.end)).missing:
        best.ratio = min(best.ratio, FRAGMENT_MIN - 0.01)  # another number or name is not a typo: it is not there
    return best


def find_fragment(fragment: str, doc: Doc) -> Found | None:
    """Where a quoted fragment is in a source, or the closest stretch and how close it is (see FRAGMENT_MIN). A `...`
    inside the quote skips text: each piece has to be there, in order. Pieces of fewer than two words are ignored."""
    pieces = [p for p in ELLIPSIS.split(fragment) if len(words(p)) >= 2]
    if not pieces:
        return None
    found: list[Found] = []
    for piece in pieces:
        f = _locate(piece, doc)
        if f is None:
            return None
        found.append(f)
    ratio = min(f.ratio for f in found)
    if any(a.start > b.start for a, b in zip(found, found[1:], strict=False)):
        ratio = min(ratio, FRAGMENT_MIN - 0.01)  # out of order
    return Found(ratio, found[0].start, found[-1].end)


def around(found: Found, doc: Doc, margin: int = 12) -> tuple[int, int]:
    """The words of the source around a found fragment, where the rest of the claim's words and numbers would be."""
    return max(0, found.start - margin), min(len(doc.words), found.end + margin)


def best_window(claim: str, doc: Doc) -> tuple[int, int]:
    """The stretch of the source (word positions) with the most of the claim's words and numbers; all of a short
    source."""
    if len(doc.words) <= WHOLE_SOURCE:
        return 0, len(doc.words)
    wanted = [w for w in content_words(claim) if w in doc.index]
    if not wanted:
        return 0, 0
    values = number_set(claim)
    starts: set[int] = set()
    for w in sorted(wanted, key=lambda w: len(doc.index[w]))[:3]:
        starts.update(max(0, pos - WINDOW // 2) for pos in doc.index[w][:CANDIDATES])
    best, best_score = (0, WINDOW), -1
    for start in sorted(starts):
        end = min(len(doc.words), start + WINDOW)
        score = sum(1 for w in wanted if (i := bisect_left(doc.index[w], start)) < len(doc.index[w])
                    and doc.index[w][i] < end)
        if values:
            score += len(values & number_set(doc.slice(start, end)))
        if score > best_score:
            best, best_score = (start, end), score
    return best
