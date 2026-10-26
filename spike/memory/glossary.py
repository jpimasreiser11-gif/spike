"""Glossaries: the user's fixed wording for terms, global or per project.

An entry is a term, the wording to use for it (a translation into `lang`, or a definition when `lang` is empty) and
an optional note. When a term appears in the conversation (the message and the last few turns; whole words or
phrases, ignoring case and accents) the entry goes into the prompt as a rule. A project's entry beats the global
one for the same term and language. Entries are plain rows in the memory database; CSV in and out use the columns
`term,translation,lang,note` (commas, semicolons or tabs are accepted on the way in).
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from spike.memory.store import GLOBAL, MemoryStore

MAX_TERM, MAX_TRANSLATION, MAX_NOTE = 200, 1000, 500
MAX_ROWS = 20_000
MAX_SCAN_CHARS = 60_000  # of the conversation looked through for terms
LANG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,19}$")
COLUMNS = ("term", "translation", "lang", "note")
ALIASES = {"term": "term", "término": "term", "termino": "term", "translation": "translation",
           "traducción": "translation", "traduccion": "translation", "definition": "translation",
           "definición": "translation", "definicion": "translation", "lang": "lang", "language": "lang",
           "idioma": "lang", "note": "note", "nota": "note", "notes": "note", "notas": "note"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, term TEXT NOT NULL, key TEXT NOT NULL, translation TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE (scope, key, lang)
);
"""


class GlossaryError(ValueError):
    """An entry or file that cannot be accepted; the message is safe to show."""


@dataclass
class Entry:
    id: str
    scope: str
    term: str
    translation: str
    lang: str
    note: str
    created: float
    updated: float

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "scope": self.scope, "term": self.term, "translation": self.translation,
                "lang": self.lang, "note": self.note, "created": self.created, "updated": self.updated}


def fold(text: str) -> str:
    """Lower case without accents and with single spaces: how terms and conversations are compared."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain.casefold()).strip()


def _entry(r: sqlite3.Row) -> Entry:
    return Entry(r["id"], r["scope"], r["term"], r["translation"], r["lang"], r["note"], r["created"], r["updated"])


def _clean(term: str, translation: str, lang: str, note: str) -> tuple[str, str, str, str]:
    term, translation, lang, note = (str(v or "").strip() for v in (term, translation, lang, note))
    if not term or not translation:
        raise GlossaryError("an entry needs a term and its wording")
    if len(term) > MAX_TERM or len(translation) > MAX_TRANSLATION or len(note) > MAX_NOTE:
        raise GlossaryError(f"too long: the term up to {MAX_TERM} characters, the wording {MAX_TRANSLATION}, "
                            f"the note {MAX_NOTE}")
    if lang and not LANG.match(lang):
        raise GlossaryError("the language is a short code such as es, en or pt-BR")
    if not fold(term):
        raise GlossaryError("the term has no letters or digits")
    return term, translation, lang, note


def _safe_cell(value: str) -> str:
    """A spreadsheet runs a cell that starts with = + - @ as a formula: a leading quote keeps it text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _unsafe_cell(value: str) -> str:
    return value[1:] if value[:1] == "'" and value[1:2] in ("=", "+", "-", "@", "\t", "\r") else value


class Glossary:
    def __init__(self, store: MemoryStore):
        self.store = store
        with store.write() as db:
            db.executescript(SCHEMA)

    # ---------------------------------------------------------------- entries
    def add(self, term: str, translation: str, lang: str = "", note: str = "", scope: str = GLOBAL) -> Entry:
        term, translation, lang, note = _clean(term, translation, lang, note)
        now = time.time()
        entry = Entry(uuid.uuid4().hex[:12], scope, term, translation, lang, note, now, now)
        try:
            with self.store.write() as db:
                self._check_room(db, scope)
                db.execute("INSERT INTO glossary VALUES (?,?,?,?,?,?,?,?,?)",
                           (entry.id, scope, term, fold(term), translation, lang, note, now, now))
        except sqlite3.IntegrityError as exc:
            raise GlossaryError(f"'{term}' is already in this glossary for that language: edit it") from exc
        return entry

    def _check_room(self, db: sqlite3.Connection, scope: str) -> None:
        if db.execute("SELECT COUNT(*) FROM glossary WHERE scope = ?", (scope,)).fetchone()[0] >= MAX_ROWS:
            raise GlossaryError(f"a glossary holds at most {MAX_ROWS} entries")

    def get(self, entry_id: str) -> Entry | None:
        with self.store.read() as db:
            r = db.execute("SELECT * FROM glossary WHERE id = ?", (entry_id,)).fetchone()
        return _entry(r) if r else None

    def update(self, entry_id: str, term: str | None = None, translation: str | None = None,
               lang: str | None = None, note: str | None = None) -> Entry | None:
        current = self.get(entry_id)
        if current is None:
            return None
        term, translation, lang, note = _clean(
            current.term if term is None else term, current.translation if translation is None else translation,
            current.lang if lang is None else lang, current.note if note is None else note)
        try:
            with self.store.write() as db:
                db.execute("UPDATE glossary SET term = ?, key = ?, translation = ?, lang = ?, note = ?, updated = ? "
                           "WHERE id = ?", (term, fold(term), translation, lang, note, time.time(), entry_id))
        except sqlite3.IntegrityError as exc:
            raise GlossaryError(f"'{term}' is already in this glossary for that language") from exc
        return self.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        with self.store.write() as db:
            return db.execute("DELETE FROM glossary WHERE id = ?", (entry_id,)).rowcount > 0

    def delete_scope(self, scope: str | None) -> int:
        with self.store.write() as db:
            if scope is None:
                return db.execute("DELETE FROM glossary").rowcount
            return db.execute("DELETE FROM glossary WHERE scope = ?", (scope,)).rowcount

    def list(self, scope: str | None = None, q: str | None = None, limit: int = 1000) -> list[Entry]:
        where, args = [], []
        if scope:
            where.append("scope = ?")
            args.append(scope)
        if q and fold(q):
            where.append("(key LIKE ? ESCAPE '\\' OR lower(translation) LIKE ? ESCAPE '\\')")
            like = "%" + fold(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [like, like]
        sql = "SELECT * FROM glossary" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self.store.read() as db:
            rows = db.execute(sql + " ORDER BY key, lang LIMIT ?", (*args, limit)).fetchall()
        return [_entry(r) for r in rows]

    # ---------------------------------------------------------------- use in a conversation
    def match(self, conversation: str, scopes: list[str]) -> list[Entry]:
        """The entries (of these scopes, the first scope winning a tie) whose term appears in the text."""
        text = fold(conversation[-MAX_SCAN_CHARS:])
        if not text:
            return []
        with self.store.read() as db:
            rows = db.execute(f"SELECT * FROM glossary WHERE scope IN ({','.join('?' * len(scopes))})",
                              scopes).fetchall()
        found: dict[tuple[str, str], Entry] = {}
        for r in sorted(rows, key=lambda r: scopes.index(r["scope"])):
            if r["key"] in text and re.search(rf"(?<!\w){re.escape(r['key'])}(?!\w)", text):
                found.setdefault((r["key"], r["lang"]), _entry(r))
        return sorted(found.values(), key=lambda e: (scopes.index(e.scope), fold(e.term), e.lang))

    # ---------------------------------------------------------------- CSV
    def export_csv(self, scope: str) -> str:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(COLUMNS)
        for e in self.list(scope=scope, limit=MAX_ROWS):
            writer.writerow([_safe_cell(v) for v in (e.term, e.translation, e.lang, e.note)])
        return out.getvalue()

    def import_csv(self, data: bytes | str, scope: str) -> dict[str, Any]:
        """Add or update entries from CSV text (an entry with the same term and language is updated). Bad rows are
        reported by line and skipped; the good ones are kept."""
        text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data.lstrip("﻿")
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
        if not rows:
            raise GlossaryError("the file has no rows")
        if len(rows) > MAX_ROWS + 1:
            raise GlossaryError(f"the file has more than {MAX_ROWS} rows")
        first = [ALIASES.get(c.strip().casefold()) for c in rows[0]]
        if "term" in first:  # a header row, in any order and language
            order, body, start = first, rows[1:], 2
        else:
            order, body, start = list(COLUMNS), rows, 1
        added = updated = 0
        errors: list[dict[str, Any]] = []
        with self.store.write() as db:  # one transaction: a large file is not committed row by row
            for line, row in enumerate(body, start):
                cells = {name: _unsafe_cell(cell.strip()) for name, cell in zip(order, row, strict=False) if name}
                try:
                    term, translation, lang, note = _clean(*(cells.get(c, "") for c in COLUMNS))
                    same = db.execute("SELECT id FROM glossary WHERE scope = ? AND key = ? AND lang = ?",
                                      (scope, fold(term), lang)).fetchone()
                    now = time.time()
                    if same is not None:
                        db.execute("UPDATE glossary SET term = ?, translation = ?, note = ?, updated = ? WHERE id = ?",
                                   (term, translation, note, now, same["id"]))
                        updated += 1
                    else:
                        self._check_room(db, scope)
                        db.execute("INSERT INTO glossary VALUES (?,?,?,?,?,?,?,?,?)", (
                            uuid.uuid4().hex[:12], scope, term, fold(term), translation, lang, note, now, now))
                        added += 1
                except GlossaryError as exc:
                    errors.append({"line": line, "error": str(exc)})
        return {"added": added, "updated": updated, "errors": errors[:50], "skipped": len(errors)}


def glossary_lines(entries: list[Entry]) -> list[str]:
    """One prompt line per entry: `term → wording (lang)` for a translation, `term: definition` without a language."""
    lines = []
    for e in entries:
        line = f"- {e.term} → {e.translation} ({e.lang})" if e.lang else f"- {e.term}: {e.translation}"
        lines.append(line + (f" [{e.note}]" if e.note else ""))
    return lines
