"""Evolution level 1: what the user asks SPIKE to remember, and their corrections, become memory.

Deterministic on purpose, so no model decides what shapes later chats: a sentence that starts with "recuerda
que…" or "a partir de ahora…" is saved at once (the user said so, in their own message), and a message that
corrects the previous answer ("No, …", "Te equivocas: …") gets a proposed rule that the user saves, edits or
drops. Spanish, English and Catalan phrasings."""

from __future__ import annotations

import re
from dataclasses import dataclass

_START = r"(?:^|(?<=[.!?\n]))[ \t]*(?:(?:por favor|please|oye|hey)[,\s]+)?"
_FROM_NOW = (r"a partir de ahora|de ahora en adelante|desde ahora|en adelante|a partir d'ara|d'ara endavant|"
             r"from now on|going forward|no vuelvas a|nunca más|never again|don'?t ever|do not ever")
_REMEMBER = re.compile(_START + r"(?:recuerda|recuérdalo|recorda|remember|no olvides|don'?t forget|do not forget)"
                       r"[ \t]*(?:que|that|:|,|-)[ \t]*(?P<body>[^\n]+)", re.I)
_STANDING = re.compile(_START + r"(?P<body>(?:" + _FROM_NOW + r")\b[^\n]+)", re.I)
_INSTRUCTION = re.compile(
    r"^(?:que\s+)?(?:" + _FROM_NOW + r"|siempre|nunca|jamás|always|never|don'?t|do not|"
    r"no (?:uses|utilices|pongas|escribas|digas|respondas|contestes|incluyas|me hables|me llames|hagas|menciones|"
    r"añadas|inventes|traduzcas|resumas)|"
    r"usa|utiliza|responde|respóndeme|contesta|contéstame|escribe|escríbeme|háblame|llámame|trátame|tutéame|"
    r"evita|incluye|pon|cita|explica|explícame|da|dame|"
    r"answer|reply|respond|write|call me|speak|talk|use|avoid|include|cite|explain|give)\b", re.I)
_ANYWHERE = re.compile(r"\b(?:siempre|nunca|always|never|sempre|mai)\b", re.I)
_PREFERENCE = re.compile(r"\b(?:prefiero|me gusta|no me gusta|me encanta|odio|i prefer|i like|i don'?t like|i love|"
                         r"i hate|m'agrada|prefereixo)\b", re.I)
_CORRECTION = re.compile(
    r"^\s*(?:no\s*[,.!:;-]+|nope[,.!:;]*|"
    r"(?:eso\s+)?no es (?:así|correcto|cierto|verdad)[,.!:;]*|(?:eso\s+)?est[áa] mal[,.!:;]*|"
    r"te equivocas[,.!:;]*|te has equivocado[,.!:;]*|te confundes[,.!:;]*|te has confundido[,.!:;]*|"
    r"incorrecto[,.!:;]*|error\s*[,.!:;]+|mal\s*[,.!:;]+|"
    r"t'equivoques[,.!:;]*|no és (?:així|correcte)[,.!:;]*|"
    r"that'?s (?:wrong|not right|incorrect|not true)[,.!:;]*|you(?:'re| are) wrong[,.!:;]*|wrong\s*[,.!:;]+|"
    r"incorrect[,.!:;]*|not quite[,.!:;]*)\s*(?P<body>\S.*)", re.I | re.S)
MIN_WORDS, MAX_CHARS = 2, 600
CORRECTION_MIN_WORDS = 4


@dataclass(frozen=True)
class Learned:
    text: str
    kind: str  # rule, preference or fact


def _sentence(body: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", body.strip(), maxsplit=1)[0].strip()
    return first[:MAX_CHARS].rstrip()


def _tidy(text: str) -> str:
    text = text.strip(" \t-–—:,;")
    return text[:1].upper() + text[1:]


def _usable(text: str, min_words: int = MIN_WORDS) -> bool:
    return len(text.split()) >= min_words and not text.endswith("?") and not text.startswith("¿")


def explicit_memories(message: str) -> list[Learned]:
    """Each sentence of the message that asks SPIKE to remember something or to keep doing something."""
    found: list[Learned] = []
    for match in _STANDING.finditer(message):
        text = _tidy(_sentence(match.group("body")))
        if _usable(text):
            found.append(Learned(text, "rule"))
    for match in _REMEMBER.finditer(message):
        text = _tidy(_sentence(match.group("body")))
        if not _usable(text):
            continue
        kind = ("rule" if _INSTRUCTION.match(text) or _ANYWHERE.search(text) else
                "preference" if _PREFERENCE.search(text) else "fact")
        found.append(Learned(text, kind))
    unique: dict[str, Learned] = {}
    for item in found:
        unique.setdefault(item.text.casefold(), item)
    return list(unique.values())


def correction_rule(message: str) -> str | None:
    """A proposed rule when the message corrects the previous answer; None when it does not look like one."""
    match = _CORRECTION.match(message)
    if not match:
        return None
    body = match.group("body").strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    text = sentences[0]
    for more in sentences[1:]:  # keep a short explanation that follows
        if len(text) + len(more) + 1 > 300:
            break
        text += " " + more
    text = _tidy(text[:MAX_CHARS])
    return text if _usable(text, CORRECTION_MIN_WORDS) else None
