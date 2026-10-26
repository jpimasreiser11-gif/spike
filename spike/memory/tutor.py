"""Tutor progress: what the learner is studying, how well they know it and when to ask again.

Each topic has a mastery level (0 to 5) and a review schedule that follows the SM-2 rule (Wozniak, 1990; the
algorithm is a published method, this code is original). After a review graded `q` from 0 (blank) to 5 (perfect):

    q < 3   the topic was forgotten: repetitions = 0, interval = 1 day, lapses + 1, ease unchanged
    q >= 3  ease += 0.1 - (5 - q) x (0.08 + (5 - q) x 0.02), never below 1.3 (it starts at 2.5);
            repetitions + 1; the interval is 1 day after the first success, 6 after the second, then
            round(previous interval x the new ease)
    next    = now + interval days

Mastery is the number of reviews passed in a row, at most 5, so a forgotten topic goes back to 0. A new topic is
due at once. A topic added with a starting mastery `m` is scheduled as if it had been passed `m` times with grade
4 (which leaves the ease at 2.5). Everything is stored in the memory database on this computer; the Education
specialist sees the topics that are due in its prompt and can record a review with the `study_review` tool.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from spike.memory.glossary import fold
from spike.memory.store import GLOBAL, MemoryStore

DAY = 86_400.0
MAX_MASTERY = 5
MIN_EASE, START_EASE = 1.3, 2.5
MAX_NAME, MAX_NOTES = 200, 1000
MAX_TOPICS = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS tutor_topics (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
  mastery INTEGER NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5, interval_days INTEGER NOT NULL DEFAULT 0,
  repetitions INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0, reviews INTEGER NOT NULL DEFAULT 0,
  last_quality INTEGER, last_review REAL, next_review REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE (scope, key)
);
CREATE INDEX IF NOT EXISTS tutor_due ON tutor_topics(scope, next_review);
"""


class TutorError(ValueError):
    """A topic or grade that cannot be accepted; the message is safe to show."""


@dataclass
class Topic:
    id: str
    scope: str
    name: str
    notes: str
    mastery: int
    ease: float
    interval_days: int
    repetitions: int
    lapses: int
    reviews: int
    last_quality: int | None
    last_review: float | None
    next_review: float
    created: float
    updated: float

    def due(self, now: float) -> bool:
        return self.next_review <= now

    def public(self, now: float) -> dict[str, Any]:
        return {"id": self.id, "scope": self.scope, "name": self.name, "notes": self.notes, "mastery": self.mastery,
                "ease": round(self.ease, 2), "interval_days": self.interval_days, "lapses": self.lapses,
                "reviews": self.reviews, "last_quality": self.last_quality, "last_review": self.last_review,
                "next_review": self.next_review, "due": self.due(now),
                "overdue_days": max(0, int((now - self.next_review) // DAY)) if self.due(now) else 0,
                "created": self.created}


def schedule(repetitions: int, interval_days: int, ease: float, quality: int) -> tuple[int, int, float]:
    """The SM-2 step: (repetitions, interval in days, ease) after a review graded `quality` (0 to 5)."""
    if quality < 0 or quality > 5:
        raise TutorError("the grade is a whole number from 0 (blank) to 5 (perfect)")
    if quality < 3:
        return 0, 1, ease
    ease = max(MIN_EASE, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    repetitions += 1
    interval = 1 if repetitions == 1 else 6 if repetitions == 2 else round(interval_days * ease)
    return repetitions, interval, ease


def _topic(r: sqlite3.Row) -> Topic:
    return Topic(r["id"], r["scope"], r["name"], r["notes"], r["mastery"], r["ease"], r["interval_days"],
                 r["repetitions"], r["lapses"], r["reviews"], r["last_quality"], r["last_review"], r["next_review"],
                 r["created"], r["updated"])


class Tutor:
    def __init__(self, store: MemoryStore, clock=time.time):
        self.store = store
        self.clock = clock
        with store.write() as db:
            db.executescript(SCHEMA)

    def add(self, name: str, scope: str = GLOBAL, notes: str = "", mastery: int = 0) -> Topic:
        name, notes = str(name or "").strip(), str(notes or "").strip()
        if not fold(name):
            raise TutorError("a topic needs a name")
        if len(name) > MAX_NAME or len(notes) > MAX_NOTES:
            raise TutorError(f"too long: the name up to {MAX_NAME} characters, the notes {MAX_NOTES}")
        if isinstance(mastery, bool) or not isinstance(mastery, int) or not 0 <= mastery <= MAX_MASTERY:
            raise TutorError(f"the starting mastery is a whole number from 0 to {MAX_MASTERY}")
        now = self.clock()
        repetitions, interval, ease = 0, 0, START_EASE
        for _ in range(mastery):  # as if it had been passed `mastery` times, with grade 4
            repetitions, interval, ease = schedule(repetitions, interval, ease, 4)
        topic = Topic(uuid.uuid4().hex[:12], scope, name, notes, mastery, ease, interval, repetitions, 0, 0, None,
                      None, now + interval * DAY, now, now)
        try:
            with self.store.write() as db:
                if db.execute("SELECT COUNT(*) FROM tutor_topics WHERE scope = ?", (scope,)).fetchone()[0] >= MAX_TOPICS:
                    raise TutorError(f"a course holds at most {MAX_TOPICS} topics")
                db.execute("INSERT INTO tutor_topics (id, scope, name, key, notes, mastery, ease, interval_days, "
                           "repetitions, lapses, reviews, last_quality, last_review, next_review, created, updated) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (topic.id, scope, name, fold(name), notes, mastery, ease, interval, repetitions, 0, 0, None,
                            None, topic.next_review, now, now))
        except sqlite3.IntegrityError as exc:
            raise TutorError(f"'{name}' is already a topic here") from exc
        return topic

    def get(self, topic_id: str) -> Topic | None:
        with self.store.read() as db:
            r = db.execute("SELECT * FROM tutor_topics WHERE id = ?", (topic_id,)).fetchone()
        return _topic(r) if r else None

    def find(self, name: str, scopes: list[str]) -> Topic | None:
        """A topic by its name (ignoring case and accents), looking in the first scope first."""
        with self.store.read() as db:
            rows = db.execute(f"SELECT * FROM tutor_topics WHERE key = ? AND scope IN ({','.join('?' * len(scopes))})",
                              (fold(name), *scopes)).fetchall()
        return min((_topic(r) for r in rows), key=lambda t: scopes.index(t.scope), default=None)

    def rename(self, topic_id: str, name: str | None = None, notes: str | None = None) -> Topic | None:
        topic = self.get(topic_id)
        if topic is None:
            return None
        name = topic.name if name is None else str(name).strip()
        notes = topic.notes if notes is None else str(notes).strip()
        if not fold(name) or len(name) > MAX_NAME or len(notes) > MAX_NOTES:
            raise TutorError("a topic needs a name of up to 200 characters; the notes up to 1000")
        try:
            with self.store.write() as db:
                db.execute("UPDATE tutor_topics SET name = ?, key = ?, notes = ?, updated = ? WHERE id = ?",
                           (name, fold(name), notes, self.clock(), topic_id))
        except sqlite3.IntegrityError as exc:
            raise TutorError(f"'{name}' is already a topic here") from exc
        return self.get(topic_id)

    def review(self, topic_id: str, quality: int) -> Topic | None:
        """Record a review graded 0 to 5 and schedule the next one (see the module doc)."""
        topic = self.get(topic_id)
        if topic is None:
            return None
        if isinstance(quality, bool) or not isinstance(quality, int):
            raise TutorError("the grade is a whole number from 0 (blank) to 5 (perfect)")
        repetitions, interval, ease = schedule(topic.repetitions, topic.interval_days, topic.ease, quality)
        now = self.clock()
        with self.store.write() as db:
            db.execute("UPDATE tutor_topics SET repetitions = ?, interval_days = ?, ease = ?, mastery = ?, "
                       "lapses = lapses + ?, reviews = reviews + 1, last_quality = ?, last_review = ?, "
                       "next_review = ?, updated = ? WHERE id = ?",
                       (repetitions, interval, ease, min(MAX_MASTERY, repetitions), int(quality < 3), quality, now,
                        now + interval * DAY, now, topic_id))
        return self.get(topic_id)

    def delete(self, topic_id: str) -> bool:
        with self.store.write() as db:
            return db.execute("DELETE FROM tutor_topics WHERE id = ?", (topic_id,)).rowcount > 0

    def delete_scope(self, scope: str | None) -> int:
        with self.store.write() as db:
            if scope is None:
                return db.execute("DELETE FROM tutor_topics").rowcount
            return db.execute("DELETE FROM tutor_topics WHERE scope = ?", (scope,)).rowcount

    def list(self, scopes: list[str] | None = None, due_only: bool = False, limit: int = 1000) -> list[Topic]:
        where, args = [], []
        if scopes:
            where.append(f"scope IN ({','.join('?' * len(scopes))})")
            args += scopes
        if due_only:
            where.append("next_review <= ?")
            args.append(self.clock())
        sql = "SELECT * FROM tutor_topics" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self.store.read() as db:
            rows = db.execute(sql + " ORDER BY next_review, key LIMIT ?", (*args, limit)).fetchall()
        return [_topic(r) for r in rows]

    def due(self, scopes: list[str], limit: int = 8) -> list[Topic]:
        """The topics to ask about now, the longest overdue first."""
        return self.list(scopes, due_only=True, limit=limit)


def tutor_section(topics: list[Topic], now: float, budget_tokens: int = 400) -> str:
    """The prompt block for the Education specialist: what is due, within a small token budget."""
    if not topics:
        return ""
    head = ("# Study progress (spaced repetition: these topics are due for review now. Quiz the learner on them when "
            "it fits the conversation, then record each result with the study_review tool, grade 0 to 5)")
    lines = []
    for t in topics:
        if not t.reviews:
            state = "new, never reviewed"
        else:
            ago = int((now - (t.last_review or now)) // DAY)
            late = int((now - t.next_review) // DAY)
            state = (f"mastery {t.mastery}/{MAX_MASTERY}, last reviewed {'today' if ago < 1 else f'{ago} days ago'}"
                     + (f", {late} days overdue" if late >= 1 else ""))
        lines.append(f"- {t.name}: {state}" + (f" ({t.notes[:120]})" if t.notes else ""))
    out = [head]
    used = len(head) // 4
    for line in lines:
        used += len(line) // 4 + 1
        if used > budget_tokens:
            break
        out.append(line)
    return "\n".join(out)
