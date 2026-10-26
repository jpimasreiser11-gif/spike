"""Deterministic entity extraction for the knowledge graph: no model, only patterns.

Finds, in this order and without overlap: links, e-mail addresses, dates (ISO, day/month/year, "3 de noviembre de
2026", "November 3, 2026"), numbers with a unit or currency ("60 días", "21 %", "12.500 €", "$40", "5 GB"), and
names: runs of capitalised words ("María García", "Banco de España", "Acme Corp"), acronyms ("ESC", "ARA-II") and
camel-case names ("PostgreSQL"). Spanish and English.

A single capitalised word that starts a sentence is the hard case ("Lucía vive en Lyon" against "Decidimos usar el
motor"). It counts as a name unless it looks like an ordinary word: it is on the stoplists below, it ends like a
verb, an adverb or an abstract noun ("-mos", "-ando", "-ción", "-mente", an infinitive, a stressed final vowel), or
it stands alone on its line like a heading. Such a word is still taken when the text also has it capitalised in the
middle of a sentence. Titles in capitals, other alphabets and lower-case names are not found. It is a cheap,
predictable first pass, not named-entity recognition: it will miss some names and keep some words.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass

KINDS = ("name", "email", "date", "quantity", "link")
MAX_SCAN = 200_000  # characters of one note that are looked at
MAX_ENTITIES = 120  # per note, most frequent first
MAX_NAME = 80

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12}
WEEKDAYS = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "monday", "tuesday",
            "wednesday", "thursday", "friday", "saturday", "sunday"}
# capitalised words that are not names when they open a run: articles, determiners, greetings
NOT_NAMES = {"el", "la", "los", "las", "un", "una", "unos", "unas", "mi", "mis", "tu", "tus", "su", "sus", "este",
             "esta", "estos", "estas", "ese", "esa", "the", "a", "an", "my", "your", "our", "this", "that", "these",
             "those", "hola", "gracias", "hello", "thanks", "si", "no", "y", "o", "and", "or", "but", "pero", "yes",
             "nuestro", "nuestra", "ok"}
# words that open a sentence and are never part of the name that follows ("Ayer Marta llamó")
OPENERS = {"ayer", "hoy", "manana", "ahora", "luego", "despues", "antes", "siempre", "nunca", "tambien", "segun",
           "cuando", "porque", "entonces", "ademas", "finalmente", "primero", "segundo", "tercero", "recuerda",
           "importante", "nota", "today", "yesterday", "tomorrow", "now", "then", "later", "after", "before", "always",
           "never", "also", "according", "when", "because", "however", "finally", "first", "next", "please",
           "remember", "note", "important", "usamos", "tengo", "tenemos", "vamos", "quiero", "necesito"}
# ordinary words that open a sentence or a line, only used to judge a lone capitalised word (see looks_common)
COMMON = {
    # es: function words, pronouns, frequent verbs and heading nouns
    "mas", "muy", "todo", "toda", "todos", "todas", "cada", "otro", "otra", "algo", "nada", "alguien", "nadie",
    "aqui", "alli", "asi", "como", "donde", "que", "quien", "esto", "eso", "aquello", "yo", "ella", "nosotros",
    "ustedes", "para", "por", "con", "sin", "sobre", "entre", "hasta", "desde", "en", "mientras", "aunque", "sino",
    "ni", "hay", "es", "son", "fue", "era", "estoy", "estamos", "tiene", "tienen", "puede", "pueden", "debe",
    "deben", "hace", "hacen", "hizo", "dijo", "pidio", "ver", "mira", "falta", "faltan", "queda", "quedan",
    "resumen", "tema", "temas", "tarea", "tareas", "idea", "ideas", "pregunta", "respuesta", "ejemplo", "caso",
    "paso", "pasos", "objetivo", "objetivos", "resultado", "resultados", "contexto", "problema", "solucion",
    "opcion", "opciones", "decision", "decisiones", "reunion", "proyecto", "notas", "lista", "pendiente",
    "pendientes", "hecho", "listo", "nuevo", "nueva", "bien", "mal", "mejor", "peor", "claro", "vale", "bueno",
    "soy", "puedo", "voy", "doy", "veo", "hago", "pongo", "debo", "sigo", "creo", "digo", "vengo", "salgo", "uso",
    "busco", "sugiero", "propongo", "prefiero", "recomiendo", "entiendo", "ayudo", "explico", "calculo", "resumo",
    # en
    "we", "you", "he", "she", "they", "here", "there", "some", "all", "any", "every", "each", "one", "to", "in",
    "on", "at", "for", "with", "from", "by", "as", "if", "so", "while", "although", "since", "unless", "what",
    "which", "who", "how", "why", "where", "is", "are", "was", "do", "does", "summary", "topic", "task", "tasks",
    "question", "answer", "example", "case", "step", "steps", "goal", "goals", "result", "results", "context",
    "problem", "solution", "option", "options", "decisions", "meeting", "project", "notes", "done", "pending",
    "ready", "see", "look", "check", "add", "use", "make", "need", "needs", "want", "wants", "let", "can", "could",
    "should", "would", "will", "must", "just", "only", "still", "already", "again", "maybe", "perhaps", "really", "very", "much", "many", "most", "more", "less", "both", "other", "another", "such", "same",
    "new", "old", "good", "bad", "best", "better", "worse", "fine", "great", "sure", "well", "right"}
CONNECTORS = r"(?:de|del|of|van|von|da|di|do|dos|das)(?:[ \t]+(?:la|las|los|el|the))?"

UNITS = (r"%|€|\$|£|eur|euros?|usd|gbp|dólares|dolares|dollars?|km/h|mph|mmhg|mg/dl|bpm|°c|°f|"
         r"kg|mg|km|cm|mm|ml|gb|mb|kb|tb|ghz|mhz|ms|min|"
         r"días?|dias?|days?|semanas?|weeks?|meses|mes|months?|años?|anos?|years?|horas?|hours?|minutos?|minutes?|"
         r"segundos?|seconds?|unidades|units|personas|people|páginas|paginas|pages|euros|puntos|points")
SHORT_UNITS = r"[gmlhsk]"  # one letter: only glued to the number ("5m", "10h")
NUMBER = r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"

LINK = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'\])]+")
EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")  # bounded: no quadratic scans
ISO_DATE = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
DMY_DATE = re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?![\d/.-])")
MONTH_NAMES = "|".join(MONTHS)
ES_DATE = re.compile(r"(?i)\b(\d{1,2})\s+de\s+(" + MONTH_NAMES + r")(?:\s+de(?:l)?\s+(\d{4}))?\b")
EN_DAY_FIRST = re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + MONTH_NAMES + r")(?:,?\s+(\d{4}))?\b")
EN_MONTH_FIRST = re.compile(r"(?i)\b(" + MONTH_NAMES + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b")
PREFIXED = re.compile(r"([€$£])[ \t]?(" + NUMBER + r")(?![\d,])")
QUANTITY = re.compile(r"(?<![\w.,])(" + NUMBER + r")(?:[ \t]?(" + UNITS + r")|(" + SHORT_UNITS + r"))(?![\w])", re.I)

TITLE = r"[A-ZÁÉÍÓÚÑÜÇ][a-záéíóúñüç]+(?:-[A-ZÁÉÍÓÚÑÜÇ][a-záéíóúñüç]+)*"
CAMEL = r"[A-Z][a-z]+(?:[A-Z][A-Za-z]*)+|[A-Z]{2,}[a-z]{2,}[A-Za-z]*"  # PostgreSQL, JavaScript, SQLite
ACRONYM = r"[A-ZÁÉÍÓÚÑ]{2,}(?:-[A-Z0-9]+)?"
WORD = re.compile(rf"(?<![\w'’-])({CAMEL}|{ACRONYM}|{TITLE})(?![\w'’])")
GAP = re.compile(rf"[ \t]+({CONNECTORS})[ \t]+")
SENTENCE_END = ".!?¡¿:;\n\r•*#>-–—|"


@dataclass(frozen=True)
class Entity:
    kind: str
    key: str
    name: str


def fold(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain.casefold()).strip()


# endings of verbs, adverbs and abstract nouns; "Valencia", "Colorado" or "Federico" are not on purpose
COMMON_ENDINGS = ("mos", "ron", "ando", "endo", "iendo", "ido", "ion", "ones", "miento", "ismo", "ing", "mente",
                  "dad", "ment", "ness", "ity", "ly")


def looks_common(word: str) -> bool:
    """Whether a single capitalised word that opens a sentence is probably just a word ("Decidimos", "Mañana",
    "Resultados"), judged from the word alone: stoplists, endings of verbs, adverbs and abstract nouns, infinitives
    and a stressed final vowel ("Revisé", "Pidió"). A name like "Lucía", "Lyon", "Toby" or "Marta" passes."""
    low = fold(word)
    if low in NOT_NAMES or low in OPENERS or low in COMMON or low in WEEKDAYS or low in MONTHS:
        return True
    if len(low) >= 6 and low.endswith(COMMON_ENDINGS):
        return True
    if len(low) >= 6 and low.endswith(("ar", "er", "ir")):
        return True
    return len(word) >= 5 and word[-1] in "éíó"


def _number(raw: str) -> str:
    """12.500,5 -> 12500.5 ; 12,500.5 -> 12500.5 ; 1,5 -> 1.5 ; 3 000 -> 3000. With both signs the last one is the
    decimal point; a lone dot or comma followed by exactly three digits after one to three digits is a group."""
    raw = raw.replace(" ", "").replace("\u00a0", "")
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal == "," else ",", "")
    elif re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    elif re.fullmatch(r"[1-9]\d{0,2}(?:,\d{3})+", raw):
        raw = raw.replace(",", "")
    return raw.replace(",", ".")


def _date(day: int, month: int, year: int | None) -> tuple[str, str] | None:
    """(key, text to show) of a real calendar date; without a year the day of every year ("--05-03", 29 Feb allowed)."""
    try:
        datetime.date(year if year is not None else 2000, month, day)
    except ValueError:
        return None
    if year is None:
        return f"--{month:02}-{day:02}", ""
    return f"{year:04}-{month:02}-{day:02}", f"{year:04}-{month:02}-{day:02}"


def extract(text: str) -> list[tuple[Entity, int]]:
    """The entities of a text with how many times each appears, most frequent first (ties: first seen)."""
    text = text[:MAX_SCAN]
    found: dict[tuple[str, str], list] = {}  # (kind, key) -> [name, count, first position]

    def note(kind: str, key: str, name: str, pos: int) -> None:
        name = re.sub(r"\s+", " ", name).strip()
        if key:
            slot = found.setdefault((kind, key), [name, 0, pos])
            slot[1] += 1

    def mask(pattern: re.Pattern, kind: str, build) -> None:
        nonlocal text

        def swap(m: re.Match) -> str:
            made = build(m)
            if made is None:
                return m.group(0)
            note(kind, made[0], made[1], m.start())
            return " " * (m.end() - m.start())

        text = pattern.sub(swap, text)

    def link(m: re.Match) -> tuple[str, str] | None:
        url = m.group(0).rstrip(".,;:!?")
        return url.lower().rstrip("/"), url

    mask(LINK, "link", link)
    mask(EMAIL, "email", lambda m: (m.group(0).lower(), m.group(0).lower()))
    for pattern, order in ((ISO_DATE, "ymd"), (DMY_DATE, "dmy"), (ES_DATE, "dmy-name"), (EN_DAY_FIRST, "dmy-name"),
                           (EN_MONTH_FIRST, "mdy-name")):
        def build_date(m: re.Match, order=order) -> tuple[str, str] | None:
            g = m.groups()
            if order == "ymd":
                made = _date(int(g[2]), int(g[1]), int(g[0]))
            elif order == "dmy":
                made = _date(int(g[0]), int(g[1]), int(g[2])) or _date(int(g[1]), int(g[0]), int(g[2]))
            elif order == "dmy-name":
                made = _date(int(g[0]), MONTHS[g[1].lower()], int(g[2]) if g[2] else None)
            else:
                made = _date(int(g[1]), MONTHS[g[0].lower()], int(g[2]) if g[2] else None)
            if made is None:
                return None
            key, shown = made
            return key, shown or m.group(0)
        mask(pattern, "date", build_date)
    mask(PREFIXED, "quantity", lambda m: (f"{_number(m.group(2))} {m.group(1)}", m.group(0)))
    mask(QUANTITY, "quantity", lambda m: (f"{_number(m.group(1))} {fold(m.group(2) or m.group(3))}",
                                          m.group(0)))

    # names: runs of capitalised words on one line, joined across "de", "del", "of"... after a single word
    runs: list[list[tuple[str, int, bool]]] = []  # parts: (text, position, is a connector)
    last_end = 0
    for m in WORD.finditer(text):
        gap = text[last_end:m.start()]
        joined = GAP.fullmatch(gap)
        if runs and re.fullmatch(r"[ \t]+", gap) and fold(m.group(1)) not in NOT_NAMES:
            runs[-1].append((m.group(1), m.start(), False))
        elif runs and joined and len(runs[-1]) == 1:
            runs[-1] += [(joined.group(1), last_end + joined.start(1), True), (m.group(1), m.start(), False)]
        else:
            runs.append([(m.group(1), m.start(), False)])  # an article starts a new run, where it is stripped
        last_end = m.end()

    def opens_sentence(pos: int) -> bool:
        i = pos - 1
        while i >= 0 and text[i] in " \t":
            i -= 1
        return i < 0 or text[i] in SENTENCE_END

    def plain(part: tuple[str, int, bool]) -> bool:
        return not part[2] and re.fullmatch(TITLE, part[0]) is not None

    def alone_on_line(pos: int, name: str) -> bool:
        """A heading: nothing else on its line but markup ("## Resumen", "**Tareas**:")."""
        i, j = pos - 1, pos + len(name)
        while i >= 0 and text[i] in " \t#*>-•":
            i -= 1
        while j < len(text) and text[j] in " \t:*":
            j += 1
        return (i < 0 or text[i] in "\n\r") and (j >= len(text) or text[j] in "\n\r")

    candidates: list[tuple[str, int, bool]] = []  # (name, position, a lone word that is probably just a word)
    for parts in runs:
        opened = opens_sentence(parts[0][1])
        stripped = False
        while parts and (fold(parts[0][0]) in NOT_NAMES or fold(parts[0][0]) in OPENERS):
            parts, stripped = parts[1:], True  # "El Cliente Norte" -> "Cliente Norte"
        while parts and fold(parts[-1][0]) in NOT_NAMES:
            parts = parts[:-1]
        if parts and opened and not stripped and len(parts) >= 2 and plain(parts[0]) and not plain(parts[1]) \
                and not parts[1][2]:
            parts = parts[1:]  # "Usamos PostgreSQL": the sentence's first word is just a word
        words = [t for t, _, connector in parts if not connector]
        if not words or all(fold(w) in WEEKDAYS or fold(w) in MONTHS for w in words):
            continue
        name = " ".join(t for t, _, _ in parts)
        if len(name) > MAX_NAME or len(parts) > 6:
            continue
        lone = opens_sentence(parts[0][1]) and len(parts) == 1 and plain(parts[0])
        doubtful = lone and (looks_common(name) or alone_on_line(parts[0][1], name))
        candidates.append((name, parts[0][1], doubtful))
    middle = {fold(n) for n, _, doubtful in candidates if not doubtful}
    for name, pos, doubtful in candidates:
        if not doubtful or fold(name) in middle:
            note("name", fold(name), name, pos)
    ranked = sorted(found.items(), key=lambda kv: (-kv[1][1], kv[1][2]))[:MAX_ENTITIES]
    return [(Entity(kind, key, slot[0]), slot[1]) for (kind, key), slot in ranked]
