"""The citation inspector: when a sentence cites a source, check by program that the source exists in this run, that
the quoted or referenced fragment is in it and that it supports the sentence.

What counts as a citation (the rule set, in order):
  1. a marked reference, `[source: notas.md]` or `(fuente: https://…)` (also `mem:`, `file:`, `url:`, `doc:`);
  2. a source named with a cue, "según notas.md", "according to report.pdf", "notas.md dice que…";
  3. a quoted passage of at least QUOTE_WORDS words («…», “…», "…") that is found in some source of the run, or of
     at least 2 words when the sentence also names or marks a source.
A bare mention ("I saved informe.md") is not a citation. A quoted passage found in no source and attributed to none
is not judged: nothing was claimed about where it comes from.

A citation passes when its source is one of the run's, the quoted fragment is there (`match.FRAGMENT_MIN`) and the
sentence is supported by the passage around it (`match.SUPPORT_MIN`, every number and name of the sentence in it).
Otherwise its status says why: no_source (fabricated source), no_fragment (fabricated fragment), unsupported (the
source exists and says something else, e.g. a changed figure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from spike.trust.evidence import Source, SourceSet
from spike.trust.match import Doc, Found, around, best_window, find_fragment, fold, support, words

QUOTE_WORDS = 4
MARKED = re.compile(r"[\[(]\s*(?:fuentes?|sources?|src|mem|memoria|memory|files?|archivos?|ficheros?|docs?|documentos?|"
                    r"documents?|urls?|p[aá]ginas?|pages?|web)\s*[:=]\s*(?P<ref>[^\])\n]{1,300})[\])]", re.I)
QUOTED = re.compile(r"«([^»]{3,600})»|“([^”]{3,600})”|\"([^\"\n]{3,600})\"")
CUE_BEFORE = re.compile(r"(?:segun|de acuerdo con|conforme a|according to|as per|as (?:stated|described|shown|noted|"
                        r"written|reported) in|(?:se )?(?:indica|dice|afirma|menciona|senala|recoge|consta|figura|"
                        r"aparece|explica) en|(?:stated|described|shown|noted|written|mentioned|listed|reported) in)"
                        r"\s+(?:(?:el|la|los|las|the)\s+)?(?:(?:archivo|fichero|documento|nota|pagina|file|document|"
                        r"note|page|source|fuente)\s+)?$")
CUE_AFTER = re.compile(r"^\s*(?:indica|dice|afirma|menciona|senala|recoge|establece|explica|contiene|says|states|"
                       r"mentions|shows|indicates|notes|reports|lists|contains)\b")
NOT_A_REF = re.compile(r"^(?:\d[\d\-/.: ]*|(?:p|pp|pag|pág|page|pages|line|lines|l)\.?\s*\d[\d\-, ]*)$", re.I)
FRAGMENT_SHOWN = 240


@dataclass
class Citation:
    ref: str  # as written, or the source's label for a quote nobody attributed
    how: str  # marked | cue | quote
    status: str  # ok | no_source | no_fragment | unsupported
    source: str = ""  # id of the source it resolved to
    label: str = ""
    quote: str = ""
    found: float | None = None  # how close the quoted fragment is to the source (1.0: word for word)
    score: float | None = None  # support of the sentence by the passage around the fragment
    missing: list[str] = field(default_factory=list)  # numbers and names the passage lacks
    fragment: str = ""  # the passage of the source it was checked against

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def public(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if v not in ("", None, [])}
        return {**out, "ok": self.ok}


def quoted(sentence: str) -> list[str]:
    return [next(g for g in m.groups() if g).strip() for m in QUOTED.finditer(sentence)]


def marked_refs(sentence: str) -> list[str]:
    """The references written in marks. One mark may hold several, split at `;`, `,`, `|`, `·` or a spaced dash;
    dates, page numbers and line numbers beside a name are not references."""
    out = []
    for m in MARKED.finditer(sentence):
        for ref in re.split(r"\s*(?:[;,|·]|\s[-–—]\s)\s*", m.group("ref")):
            if ref.strip() and not NOT_A_REF.match(ref.strip()):
                out.append(ref.strip())
    return out


def _cue_at(folded: str, alias: str) -> bool:
    for m in re.finditer(rf"(?<![\w/.-]){re.escape(alias)}(?![\w-])", folded):
        if CUE_BEFORE.search(folded[:m.start()].rstrip().rstrip(":,") + " ") or CUE_AFTER.match(folded[m.end():]):
            return True
    return False


def cued(sentence: str, sources: SourceSet) -> list[Source]:
    """Sources the sentence names with a cue ('según notas.md', 'notas.md dice')."""
    folded = fold(sentence)
    return [s for s in sources.mentioned(sentence) if any(_cue_at(folded, a) for a in s.aliases)]


def core(sentence: str, sources: list[Source]) -> str:
    """The sentence as a claim: without its citation marks or the names of the sources it cites."""
    text = MARKED.sub(" ", sentence)
    for source in sources:
        for name in sorted(source.names, key=len, reverse=True):
            text = re.sub(re.escape(name), " ", text, flags=re.I)
    return text


def _shown(passage: str) -> str:
    return passage[:FRAGMENT_SHOWN] + ("…" if len(passage) > FRAGMENT_SHOWN else "")


def _check(claim: str, ref: str, how: str, candidates: list[Source], quotes: list[str]) -> list[Citation]:
    """One citation: the claim against the best of the sources it may mean, once per quoted fragment."""
    out: list[Citation] = []
    for quote in quotes or [""]:
        best: tuple[float, Citation] | None = None
        for source in candidates:
            doc: Doc = source.doc
            found: Found | None = find_fragment(quote, doc) if quote else None
            if quote and (found is None or not found.ok):
                c = Citation(ref, how, "no_fragment", source.id, source.label, quote, found.ratio if found else 0.0)
                rank = c.found or 0.0
            else:
                a, b = around(found, doc) if found else best_window(claim, doc)
                passage = doc.slice(a, b)
                sup = support(claim, f"{source.context} {passage}" if source.context else passage)
                c = Citation(ref, how, "ok" if sup.ok else "unsupported", source.id, source.label, quote,
                             found.ratio if found else None, sup.score, sup.missing, _shown(doc.shown(a, b)))
                rank = 1 + sup.score
            if best is None or rank > best[0]:
                best = (rank, c)
        if best is not None:
            out.append(best[1])
    return out


def inspect(sentence: str, sources: SourceSet) -> tuple[list[Citation], str]:
    """The citations in a sentence, each checked, and the claim text the sentence makes without them."""
    found: list[Citation] = []
    quotes = quoted(sentence)
    cited: list[tuple[str, str, list[Source]]] = []  # (ref, how, sources it may mean)
    for ref in marked_refs(sentence):
        cited.append((ref, "marked", sources.resolve(ref)))
    for source in cued(sentence, sources):
        if not any(source in s for _, _, s in cited):
            cited.append((source.label, "cue", [source]))
    claim = core(sentence, [s for _, _, group in cited for s in group])
    for ref, how, group in cited:
        if not group:
            found.append(Citation(ref, how, "no_source"))
            continue
        checked = _check(claim, ref, how, group, [q for q in quotes if len(words(q)) >= 2])
        authored = all(s.authored for s in group)  # the model's own file: describing it is not claiming from it
        found += [c for c in checked if c.ok or not authored]
    if not cited:
        mine = [s for s in sources.items if not s.authored]
        for quote in (q for q in quotes if len(words(q)) >= QUOTE_WORDS):
            hits = [(find_fragment(quote, s.doc), s) for s in mine]
            hits = [(f, s) for f, s in hits if f is not None and f.ok]
            if hits:
                _, source = max(hits, key=lambda h: h[0].ratio)
                found += _check(claim, source.label, "quote", [source], [quote])
    return found, claim
