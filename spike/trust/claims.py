"""Claim labels. After an answer is written it is split into claims (sentences, list items, table rows) and each is
labelled by a fixed rule set; no model decides that a claim is verified.

Rules, in this order, for each claim:
  1. A citation in the claim fails (source not in the run, quoted fragment not in the source, or the passage does not
     support it: a number or name of the claim is absent from it) -> `unchecked`.
  2. The claim has citations and they all pass -> `verified`.
  3. No citation, but a source of the run backs it (`backing`): a tool's result, what code or a command printed, a
     page, file or recalled note that has the claim's numbers, names and at least half its words, or the user's own
     words restated -> `verified`. Something the model wrote itself (write_file) backs a claim only when the claim
     names it.
  4. The claim hedges ("probablemente", "might"), infers ("por tanto", "therefore"), advises ("te recomiendo",
     "you should"), is conditional ("Si…", "If…"), or is too generic to check (no number, no name, fewer than
     GENERIC_WORDS content words) -> `hypothesis`.
  5. Anything else is a statement of fact nothing backs -> `unchecked`.
Not claims, so not labelled: code blocks, headings, questions, sentences ending in ":", greetings and offers.
An optional model pass (`parse_downgrades`) may lower a label (verified -> hypothesis -> unchecked), never raise one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from spike.orchestrator.planner import extract_json
from spike.trust.citations import Citation, core, inspect
from spike.trust.evidence import Evidence, Source, SourceSet
from spike.trust.match import best_window, content_words, fold, names, numbers, support, words

LABELS = ("verified", "hypothesis", "unchecked")
RANK = {"unchecked": 0, "hypothesis": 1, "verified": 2}
MAX_CLAIMS = 60
MAX_SOURCES = 30
MAX_TEXT = 400
GENERIC_WORDS = 6

FENCE = re.compile(r"^\s*(```|~~~)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+")
HEADING = re.compile(r"^\s*#{1,6}\s")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
EMPHASIS = re.compile(r"\*\*|__|\*|`|~~")
BOUNDARY = re.compile(r"[.!?…]+[\"»”’')\]]*\s+")
ABBREVIATIONS = {"sr", "sra", "srta", "dr", "dra", "prof", "ing", "lic", "vs", "pag", "num", "cap", "art", "ej", "eg",
                 "ie", "mr", "mrs", "ms", "st", "inc", "ltd", "fig"}
GREETING = re.compile(
    r"^(?:aqui (?:tienes|esta|estan|van|te dejo)|a continuacion|espero que|si (?:necesitas|quieres|prefieres|te interesa|"
    r"lo deseas)|no dudes|avisame|dime si|hola\b|buenas\b|gracias|here(?: is|'s| are)|below (?:is|are)|i hope|if you "
    r"(?:need|want|prefer|would like)|let me know|feel free|hello\b|thanks|thank you|lo siento|i'm sorry|sorry\b|"
    r"happy to help|i can help|puedo ayudarte)")
SHORT_GREETING = re.compile(r"^(?:claro|por supuesto|vale|perfecto|entendido|de nada|sure|of course|great|got it|"
                            r"certainly|absolutely)\b")


def _rx(phrases: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases.split("|")) + r")\b")


HEDGES = _rx("probablemente|posiblemente|quiza|quizas|tal vez|acaso|podria|podrian|pudiera|puede que|puede ser que|"
             "es posible|es probable|parece|parecen|pareceria|al parecer|aparentemente|supuestamente|creo|creemos|"
             "pienso|supongo|imagino|diria|me parece|en mi opinion|a mi juicio|seguramente|presumiblemente|"
             "no estoy seguro|no estoy segura|no tengo certeza|no puedo confirmar|no puedo verificar|"
             "si no me equivoco|que yo sepa|habria|seria|serian|tendria|se cree|se estima|se supone|"
             "probably|possibly|perhaps|maybe|might|could|seems|seem|seemingly|appears to|apparently|presumably|"
             "likely|unlikely|i think|i believe|i guess|i suppose|i assume|i would say|i'd say|in my opinion|"
             "as far as i know|not sure|it is possible|it's possible|supposedly|allegedly|reportedly|tends to")
INFERENCES = _rx("por tanto|por lo tanto|por consiguiente|en consecuencia|asi que|de modo que|de ahi que|se deduce|"
                 "se infiere|esto implica|esto significa|esto sugiere|lo que implica|lo que significa|lo cual implica|"
                 "lo cual sugiere|cabe esperar|es de esperar|deduzco|concluyo|en conclusion|therefore|thus|hence|"
                 "consequently|this means|this implies|this suggests|which means|which implies|which suggests|it follows|"
                 "we can infer|i infer|i conclude|in conclusion|as a result")
ADVICE = _rx("recomiendo|te recomiendo|recomendamos|aconsejo|sugiero|te sugiero|conviene|convendria|es mejor|"
             "lo mejor es|lo ideal es|deberias|deberia|deberian|habria que|puedes|podrias|podeis|una opcion es|"
             "una buena idea|vale la pena|merece la pena|i recommend|i suggest|you should|you could|you can|you might|"
             "consider|it is best|it's best|the best way|ideally|better to|my advice|you may want to|i'd recommend|"
             "it is advisable")
CONDITIONAL = re.compile(r"^\W*(?:Si|si|If|if|En caso de|en caso de|In case|in case|Unless|unless|A menos que|a menos que)\s")


@dataclass
class Claim:
    id: str
    text: str
    label: str  # verified | hypothesis | unchecked
    why: str  # the rule that gave the label (see WHY in the web app's i18n)
    basis: list[dict[str, Any]] = field(default_factory=list)  # what backs it: {"kind", "label", "score"}
    citations: list[Citation] = field(default_factory=list)
    downgraded: bool = False  # lowered by the optional model pass

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "label": self.label, "why": self.why,
                **({"basis": self.basis} if self.basis else {}),
                **({"citations": [c.public() for c in self.citations]} if self.citations else {}),
                **({"downgraded": True} if self.downgraded else {})}


@dataclass
class Report:
    claims: list[Claim]
    sources: list[Source]
    skipped: int = 0  # claims past MAX_CLAIMS, not labelled
    model_pass: dict[str, Any] | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {label: sum(1 for c in self.claims if c.label == label) for label in LABELS}

    def public(self) -> dict[str, Any]:
        return {"claims": [c.public() for c in self.claims], "counts": self.counts,
                "sources": [s.public() for s in self.sources if s.kind != "user"][:MAX_SOURCES],
                **({"skipped": self.skipped} if self.skipped else {}),
                **({"model_pass": self.model_pass} if self.model_pass else {})}


# ------------------------------------------------------------------------------------------------ splitting
def clean(text: str) -> str:
    return " ".join(EMPHASIS.sub("", LINK.sub(r"\1", text)).split())


def sentences(paragraph: str) -> list[str]:
    """A paragraph cut after `.`, `!`, `?` or `…` when a capital letter, a digit or an opening mark follows; not
    after an abbreviation ('Sr.', 'p. ej.') or an initial."""
    out, start = [], 0
    for m in BOUNDARY.finditer(paragraph):
        nxt = paragraph[m.end():m.end() + 1]
        if not nxt or not (nxt.isupper() or nxt.isdigit() or nxt in "¿¡\"«“([-•*"):
            continue
        before = paragraph[start:m.start()]
        previous = re.findall(r"\w+", before)[-1:]
        unit = re.search(r"\d\s*\w+$", before)  # '35 ms.' ends a sentence: 'ms' there is a unit, not 'Ms.'
        if m.group().startswith(".") and previous and not unit and (
                previous[0].lower() in ABBREVIATIONS or (len(previous[0]) == 1 and previous[0].isalpha())):
            continue
        out.append(paragraph[start:m.end()].strip())
        start = m.end()
    out.append(paragraph[start:].strip())
    return [s for s in out if s]


def units(answer: str) -> list[str]:
    """The answer's sentences, list items and table rows, markdown stripped. Code blocks, headings, a table's
    header and separator rows are left out."""
    out: list[str] = []
    paragraph: list[str] = []
    fenced = False

    def flush() -> None:
        if paragraph:
            out.extend(sentences(clean(" ".join(paragraph))))
            paragraph.clear()

    lines = answer.splitlines()
    for i, line in enumerate(lines):
        if FENCE.match(line):
            flush()
            fenced = not fenced
        elif fenced:
            continue
        elif not line.strip() or HEADING.match(line):
            flush()
        elif line.lstrip().startswith("|"):
            flush()
            following = lines[i + 1] if i + 1 < len(lines) else ""
            if not TABLE_SEP.match(line) and not TABLE_SEP.match(following):
                cells = [clean(c) for c in line.strip().strip("|").split("|")]
                out.append(" · ".join(c for c in cells if c))
        elif m := LIST_ITEM.match(line):
            flush()
            paragraph.append(line[m.end():].strip())
        else:
            paragraph.append(line.strip().lstrip(">").strip())
    flush()
    return out


def is_claim(sentence: str) -> bool:
    folded = fold(sentence).strip()
    w = words(sentence)
    if not w or not any(c.isalpha() for c in sentence):
        return False
    if sentence.endswith(("?", ":")) or sentence.startswith("¿"):
        return False
    if GREETING.match(folded) or (SHORT_GREETING.match(folded) and len(w) <= 6):
        return False
    return len(w) >= 3 or (len(w) >= 2 and any(c.isdigit() for c in sentence))


def split_claims(answer: str) -> list[str]:
    return [s for s in units(answer) if is_claim(s)]


# ------------------------------------------------------------------------------------------------ labelling
def hedge(sentence: str) -> str:
    """Why a sentence presents itself as reasoning, not as a report of fact ('' if it does not)."""
    folded = fold(sentence)
    if CONDITIONAL.match(sentence):
        return "conditional"
    for why, pattern in (("hedged", HEDGES), ("inference", INFERENCES), ("advice", ADVICE)):
        if pattern.search(folded):
            return why
    return ""


def generic(sentence: str) -> bool:
    """Nothing to check in it: no number, no name, no quote, and few content words."""
    return not numbers(sentence) and not names(sentence) and '"' not in sentence and "«" not in sentence \
        and len(content_words(sentence)) < GENERIC_WORDS


def backing(sentence: str, sources: SourceSet) -> tuple[Source, float] | None:
    """The source of the run that backs a sentence nothing cites (rule 3), with how well, or None."""
    best: tuple[Source, float] | None = None
    named = sources.mentioned(sentence)
    ordered = [s for s in sources.items if s.kind != "user"] + [s for s in sources.items if s.kind == "user"]
    for source in ordered:
        if source.authored and source not in named:
            continue
        claim = core(sentence, [source]) if source.authored else sentence
        passage = source.doc.slice(*best_window(claim, source.doc))
        if source.context:  # a tool's own arguments may have the numbers, but its result must tie to the claim
            with_context = support(claim, f"{source.context} {passage}", acronyms=False)
            ok = with_context.backs and support(claim, passage, acronyms=False).anchors >= 1
        else:
            with_context = support(claim, passage)
            ok = with_context.backs
        if ok and (best is None or with_context.score > best[1]):
            best = (source, with_context.score)
    return best


def label_one(index: int, sentence: str, sources: SourceSet) -> Claim:
    text = sentence[:MAX_TEXT]
    citations, claim_text = inspect(sentence, sources)
    cid = f"c{index}"
    if any(not c.ok for c in citations):
        return Claim(cid, text, "unchecked", "citation_failed", citations=citations)
    if citations:
        basis = [{"kind": next((s.kind for s in sources.items if s.id == c.source), "memory"), "label": c.label,
                  "score": c.score} for c in citations]
        return Claim(cid, text, "verified", "cited", basis, citations)
    found = backing(sentence, sources)
    if found is not None:
        source, score = found
        return Claim(cid, text, "verified", source.kind, [{"kind": source.kind, "label": source.label, "score": score}])
    if why := hedge(sentence):
        return Claim(cid, text, "hypothesis", why)
    if generic(claim_text):
        return Claim(cid, text, "hypothesis", "generic")
    return Claim(cid, text, "unchecked", "unbacked")


def analyse(answer: str, evidence: Evidence) -> Report:
    """Split an answer into claims and label each against the evidence of its run."""
    found = split_claims(answer)
    claims = [label_one(i, s, evidence.sources) for i, s in enumerate(found[:MAX_CLAIMS], 1)]
    return Report(claims=claims, sources=evidence.sources.items, skipped=max(0, len(found) - MAX_CLAIMS))


# ------------------------------------------------------------------------------------------------ model pass
def downgrade_prompt(claims: list[Claim]) -> str:
    rows = "\n".join(f"{c.id} [{c.label}; {c.why}]: {c.text}" for c in claims)
    return ("A program labelled these claims from an answer. verified = a source of the run backs it; hypothesis = "
            "the answer hedges or infers; unchecked = stated as fact, nothing backs it. Reply with JSON only: "
            '{"downgrade": [{"id": "c1", "label": "hypothesis" or "unchecked"}]} listing only the claims whose '
            "label is too generous (a verified claim whose wording says more than its source, or an invented "
            "detail). Never list a claim to raise its label. An empty list is a good answer.\n\n" + rows)


def parse_downgrades(text: str, claims: list[Claim]) -> dict[str, str]:
    """The model pass's verdict as {claim id: new label}, keeping only changes that LOWER a label."""
    obj = extract_json(text)
    out: dict[str, str] = {}
    by_id = {c.id: c for c in claims}
    rows = (obj or {}).get("downgrade")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        claim, new = by_id.get(str(row.get("id"))), row.get("label")
        if claim is not None and new in RANK and RANK[new] < RANK[claim.label]:
            out[claim.id] = new
    return out


def apply_downgrades(report: Report, downgrades: dict[str, str]) -> int:
    changed = 0
    for claim in report.claims:
        new = downgrades.get(claim.id)
        if new in RANK and RANK[new] < RANK[claim.label]:  # never up
            claim.label, claim.downgraded = new, True
            changed += 1
    return changed
