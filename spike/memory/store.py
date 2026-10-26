"""SQLite store for memories.

One row per memory; its text is split into chunks, each indexed by FTS5 (BM25 over words) and, once an embedding
model has seen it, by a normalised vector stored next to the chunk. Search fuses both rankings (reciprocal rank
fusion). Deleting a memory deletes its chunks, their index entries and their vectors; `secure_delete` overwrites
the freed pages and the word index is merged so the deleted text does not linger in the file.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from spike.skills.engine import STOPWORDS

KINDS = ("fact", "decision", "preference", "rule", "summary", "document")
GLOBAL = "global"
CHUNK_CHARS = 900  # ≈ 250 tokens
MAX_CHUNKS = 2000
MAX_TEXT = 2_000_000
RRF_K = 60
CANDIDATES = 50
# Cosine floor for a chunk found only by meaning (no shared words). Unmeasured: to be calibrated against the real
# embedding model before it is presented as tuned.
VECTOR_MIN = 0.45

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  meta TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_scope ON memories(scope, kind);
CREATE INDEX IF NOT EXISTS memories_source ON memories(scope, source);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE, ord INTEGER NOT NULL,
  text TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunks_memory ON chunks(memory_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""


@dataclass
class Memory:
    id: str
    scope: str
    kind: str
    text: str
    source: str
    created: float
    updated: float
    meta: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "scope": self.scope, "kind": self.kind, "text": self.text, "source": self.source,
                "created": self.created, "updated": self.updated, "meta": self.meta}


@dataclass
class Hit:
    memory: Memory
    text: str  # the chunk that matched
    score: float
    by: list[str]  # "words" and/or "meaning"


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split at blank lines, joining short paragraphs and cutting long ones at a sentence end or space."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        while len(para) > size:
            cut = max(para.rfind(". ", 0, size), para.rfind("\n", 0, size), para.rfind(" ", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return [c for c in chunks if c][:MAX_CHUNKS]


def fts_query(text: str) -> str:
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) > 1 and w not in STOPWORDS]
    return " OR ".join(f'"{w}"' for w in list(dict.fromkeys(words))[:32])


def _row(r: sqlite3.Row) -> Memory:
    return Memory(id=r["id"], scope=r["scope"], kind=r["kind"], text=r["text"], source=r["source"],
                  created=r["created"], updated=r["updated"], meta=json.loads(r["meta"] or "{}"))


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA secure_delete = ON")
        self._db.executescript(SCHEMA)
        self._version = 0
        self._vector_cache: dict[tuple, tuple[int, np.ndarray, np.ndarray]] = {}

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """The connection under the store's lock, for the modules that keep their own tables in this file."""
        with self._lock:
            yield self._db

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One transaction under the store's lock; cached vectors are dropped afterwards."""
        with self._lock, self._db:
            yield self._db
            self._version += 1

    # ---------------------------------------------------------------- writes
    def add(self, text: str, kind: str, scope: str = GLOBAL, source: str = "",
            meta: dict[str, Any] | None = None) -> Memory:
        text = text.strip()
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if not text:
            raise ValueError("a memory needs text")
        if len(text) > MAX_TEXT:
            raise ValueError("the text is too long for one memory")
        now = time.time()
        memory = Memory(id=uuid.uuid4().hex[:16], scope=scope, kind=kind, text=text, source=source, created=now,
                        updated=now, meta=dict(meta or {}))
        with self._lock, self._db:
            self._db.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?)",
                             (memory.id, scope, kind, text, source, json.dumps(memory.meta), now, now))
            self._insert_chunks(memory.id, text)
            self._version += 1
        return memory

    def _insert_chunks(self, memory_id: str, text: str) -> None:
        self._db.executemany("INSERT INTO chunks (memory_id, ord, text) VALUES (?,?,?)",
                             [(memory_id, i, c) for i, c in enumerate(chunk_text(text))])

    def replace_source(self, scope: str, source: str, text: str, kind: str,
                       meta: dict[str, Any] | None = None) -> Memory:
        """One memory per (scope, source): a re-uploaded file or a newer chat summary replaces the old one."""
        with self._lock:
            self.delete_source(scope, source, optimize=False)
            return self.add(text, kind, scope, source, meta)

    def update(self, memory_id: str, text: str | None = None, kind: str | None = None) -> Memory | None:
        current = self.get(memory_id)
        if current is None:
            return None
        if kind is not None and kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        new_text = current.text if text is None else text.strip()
        if not new_text:
            raise ValueError("a memory needs text")
        with self._lock, self._db:
            self._db.execute("UPDATE memories SET text = ?, kind = ?, updated = ? WHERE id = ?",
                             (new_text, kind or current.kind, time.time(), memory_id))
            if new_text != current.text:
                self._db.execute("DELETE FROM chunks WHERE memory_id = ?", (memory_id,))
                self._insert_chunks(memory_id, new_text)
            self._version += 1
        return self.get(memory_id)

    def _delete_where(self, where: str, args: tuple, optimize: bool) -> int:
        with self._lock:
            with self._db:
                n = self._db.execute(f"DELETE FROM memories WHERE {where}", args).rowcount
                self._version += 1
            if n and optimize:
                # merge the word index so deleted terms leave the file (secure_delete zeroes the freed pages)
                with self._db:
                    self._db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
        return n

    def delete_where(self, where: str, args: tuple = (), optimize: bool = True) -> int:
        """Delete the memories matching a WHERE clause on `memories` (their chunks, index entries and vectors go too)."""
        return self._delete_where(where, args, optimize)

    def delete(self, memory_id: str) -> bool:
        return self._delete_where("id = ?", (memory_id,), True) > 0

    def delete_source(self, scope: str, source: str, optimize: bool = True) -> int:
        return self._delete_where("scope = ? AND source = ?", (scope, source), optimize)

    def delete_scope(self, scope: str) -> int:
        return self._delete_where("scope = ?", (scope,), True)

    def clear(self) -> int:
        return self._delete_where("1 = 1", (), True)

    # ---------------------------------------------------------------- reads
    def get(self, memory_id: str) -> Memory | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _row(r) if r else None

    def find_source(self, scope: str, source: str) -> Memory | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM memories WHERE scope = ? AND source = ?", (scope, source)).fetchone()
        return _row(r) if r else None

    def find_text(self, scope: str, kind: str, text: str) -> Memory | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM memories WHERE scope = ? AND kind = ? "  # a final full stop aside
                                 "AND rtrim(text, '. ') = ? COLLATE NOCASE",
                                 (scope, kind, text.strip().rstrip(". "))).fetchone()
        return _row(r) if r else None

    def list(self, scope: str | None = None, kind: str | None = None, limit: int = 200,
             offset: int = 0) -> list[Memory]:
        where, args = [], []
        if scope:
            where.append("scope = ?")
            args.append(scope)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        sql = "SELECT * FROM memories" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY updated DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return [_row(r) for r in rows]

    def rules(self, scopes: list[str]) -> list[Memory]:
        marks = ",".join("?" * len(scopes))
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM memories WHERE kind = 'rule' AND scope IN ({marks}) "
                                    "ORDER BY updated DESC", scopes).fetchall()
        return [_row(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            memories = self._db.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall()
            chunks = self._db.execute("SELECT COUNT(*), COUNT(embedding) FROM chunks").fetchone()
        return {"memories": sum(n for _, n in memories), "by_kind": {k: n for k, n in memories},
                "chunks": chunks[0], "embedded": chunks[1]}

    # ---------------------------------------------------------------- vectors
    def pending(self, model: str, limit: int = 64) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._db.execute("SELECT id, text FROM chunks WHERE embedding IS NULL OR model != ? LIMIT ?",
                                    (model, limit)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def set_embeddings(self, model: str, items: list[tuple[int, list[float]]]) -> None:
        rows = []
        for chunk_id, vector in items:
            v = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(v))
            rows.append((model, (v / norm if norm else v).astype(np.float16).tobytes(), chunk_id))
        with self._lock, self._db:
            self._db.executemany("UPDATE chunks SET model = ?, embedding = ? WHERE id = ?", rows)
            self._version += 1

    def _vectors(self, scopes: list[str], kinds: list[str], model: str) -> tuple[np.ndarray, np.ndarray]:
        key = (tuple(scopes), tuple(kinds), model)
        cached = self._vector_cache.get(key)
        if cached and cached[0] == self._version:
            return cached[1], cached[2]
        with self._lock:
            rows = self._db.execute(
                f"SELECT c.id, c.embedding FROM chunks c JOIN memories m ON m.id = c.memory_id "
                f"WHERE c.model = ? AND c.embedding IS NOT NULL AND m.scope IN ({','.join('?' * len(scopes))}) "
                f"AND m.kind IN ({','.join('?' * len(kinds))})", (model, *scopes, *kinds)).fetchall()
        dims = {len(r[1]) for r in rows}
        size = max(dims, key=lambda d: sum(len(r[1]) == d for r in rows)) if dims else 0
        rows = [r for r in rows if len(r[1]) == size]  # a model change mid-way: keep the dominant dimension
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        matrix = (np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float16).reshape(len(rows), -1)
                  .astype(np.float32) if rows else np.zeros((0, 0), dtype=np.float32))
        self._vector_cache = {key: (self._version, ids, matrix)}
        return ids, matrix

    # ---------------------------------------------------------------- search
    def search(self, query: str, scopes: list[str], query_vector: list[float] | None = None, model: str = "",
               k: int = 6, kinds: list[str] | None = None, per_memory: int = 2) -> list[Hit]:
        kinds = kinds or [x for x in KINDS if x != "rule"]
        ranks: dict[int, dict[str, int]] = {}
        match = fts_query(query)
        if match:
            with self._lock:
                rows = self._db.execute(
                    "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                    "JOIN memories m ON m.id = c.memory_id WHERE chunks_fts MATCH ? "
                    f"AND m.scope IN ({','.join('?' * len(scopes))}) AND m.kind IN ({','.join('?' * len(kinds))}) "
                    "ORDER BY bm25(chunks_fts) LIMIT ?", (match, *scopes, *kinds, CANDIDATES)).fetchall()
            for rank, r in enumerate(rows):
                ranks.setdefault(r[0], {})["words"] = rank
        if query_vector is not None and model:
            ids, matrix = self._vectors(scopes, kinds, model)
            q = np.asarray(query_vector, dtype=np.float32)
            if len(ids) and matrix.shape[1] == q.shape[0] and np.linalg.norm(q):
                sims = matrix @ (q / np.linalg.norm(q))
                order = np.argsort(-sims)[:CANDIDATES]
                rank = 0
                for i in order:
                    chunk_id = int(ids[i])
                    if sims[i] >= VECTOR_MIN or chunk_id in ranks:  # word matches keep their meaning rank too
                        ranks.setdefault(chunk_id, {})["meaning"] = rank
                        rank += 1
        if not ranks:
            return []
        fused = sorted(ranks, key=lambda c: -sum(1 / (RRF_K + r) for r in ranks[c].values()))
        with self._lock:
            marks = ",".join("?" * len(fused))
            rows = {r["cid"]: r for r in self._db.execute(
                f"SELECT c.id AS cid, c.text AS ctext, m.* FROM chunks c JOIN memories m ON m.id = c.memory_id "
                f"WHERE c.id IN ({marks})", fused).fetchall()}
        hits: list[Hit] = []
        taken: dict[str, int] = {}
        for chunk_id in fused:
            r = rows.get(chunk_id)
            if r is None or taken.get(r["id"], 0) >= per_memory:
                continue
            taken[r["id"]] = taken.get(r["id"], 0) + 1
            score = sum(1 / (RRF_K + x) for x in ranks[chunk_id].values())
            hits.append(Hit(memory=_row(r), text=r["ctext"], score=round(score, 5), by=sorted(ranks[chunk_id])))
            if len(hits) >= k:
                break
        return hits

    # ---------------------------------------------------------------- export / import
    def export(self, scope: str | None = None) -> list[dict[str, Any]]:
        return [m.public() for m in self.list(scope=scope, limit=1_000_000)]

    def import_items(self, items: list[dict[str, Any]]) -> int:
        added = 0
        for item in items:
            if not isinstance(item, dict) or item.get("kind") not in KINDS or not str(item.get("text", "")).strip():
                raise ValueError("each memory needs 'text' and a valid 'kind'")
        for item in items:
            scope = str(item.get("scope") or GLOBAL)
            source = str(item.get("source") or "")
            if source and self.find_source(scope, source):
                self.replace_source(scope, source, str(item["text"]), item["kind"], item.get("meta"))
            else:
                self.add(str(item["text"]), item["kind"], scope, source, item.get("meta"))
            added += 1
        return added
