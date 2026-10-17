"""Local persistence: conversations, messages, settings and provider configurations (SQLite)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
  mode TEXT NOT NULL DEFAULT 'auto', provider_id TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_conv ON messages(conversation_id, created);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS providers (id TEXT PRIMARY KEY, config TEXT NOT NULL, created REAL NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    # -------------------------------------------------------------- conversations
    def create_conversation(self, title: str = "New chat", mode: str = "auto", provider_id: str | None = None) -> dict:
        now = time.time()
        cid = uuid.uuid4().hex
        self._exec("INSERT INTO conversations VALUES (?,?,?,?,?,?)", (cid, title, now, now, mode, provider_id))
        return self.get_conversation(cid)

    def get_conversation(self, cid: str) -> dict | None:
        rows = self._exec("SELECT * FROM conversations WHERE id=?", (cid,))
        return dict(rows[0]) if rows else None

    def list_conversations(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,))]

    def update_conversation(self, cid: str, **fields: Any) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "mode", "provider_id"}}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE conversations SET {sets}, updated=? WHERE id=?", (*allowed.values(), time.time(), cid))
        return self.get_conversation(cid)

    def delete_conversation(self, cid: str) -> None:
        self._exec("DELETE FROM conversations WHERE id=?", (cid,))

    # -------------------------------------------------------------- messages
    def add_message(self, cid: str, role: str, content: str, meta: dict | None = None) -> dict:
        mid, now = uuid.uuid4().hex, time.time()
        self._exec("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                   (mid, cid, role, content, json.dumps(meta or {}, ensure_ascii=False), now))
        self._exec("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
        return {"id": mid, "conversation_id": cid, "role": role, "content": content, "meta": meta or {}, "created": now}

    def messages(self, cid: str) -> list[dict]:
        rows = self._exec("SELECT * FROM messages WHERE conversation_id=? ORDER BY created", (cid,))
        return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]

    # -------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._exec("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))

    # -------------------------------------------------------------- providers
    def save_provider(self, config: dict) -> None:
        config = {k: v for k, v in config.items() if k != "api_key"}  # secrets never go into the database
        self._exec("INSERT INTO providers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",
                   (config["id"], json.dumps(config, ensure_ascii=False), time.time()))

    def list_providers(self) -> list[dict]:
        return [json.loads(r["config"]) for r in self._exec("SELECT config FROM providers ORDER BY created")]

    def delete_provider(self, pid: str) -> None:
        self._exec("DELETE FROM providers WHERE id=?", (pid,))
