"""Local persistence: conversations, messages, settings, provider configurations and the call log (SQLite)."""

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
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, instructions TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'auto',
  created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, provider_id TEXT NOT NULL, provider TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '', local INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, estimated INTEGER NOT NULL DEFAULT 0,
  cost REAL, files_sent INTEGER NOT NULL DEFAULT 0, files_withheld INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS calls_by_provider ON calls(provider_id, ts);
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, call_id TEXT NOT NULL, tool TEXT NOT NULL, created REAL NOT NULL,
  undone REAL, files TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_by_conv ON checkpoints(conversation_id, created);
"""
CALL_LOG_DAYS = 400  # older entries of the call log are dropped when SPIKE starts
PROJECT_FIELDS = {"name", "instructions", "mode"}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(conversations)")}
        if "project_id" not in columns:  # databases created before projects existed
            self._conn.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        self._conn.execute("DELETE FROM calls WHERE ts < ?", (time.time() - CALL_LOG_DAYS * 86400,))
        self._conn.commit()
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    # -------------------------------------------------------------- conversations
    def create_conversation(self, title: str = "New chat", mode: str = "auto", provider_id: str | None = None,
                            project_id: str | None = None, created: float | None = None,
                            updated: float | None = None) -> dict:
        now = time.time()
        cid = uuid.uuid4().hex
        self._exec("INSERT INTO conversations (id, title, created, updated, mode, provider_id, project_id) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (cid, title, created or now, updated or created or now, mode, provider_id, project_id))
        return self.get_conversation(cid)

    def get_conversation(self, cid: str) -> dict | None:
        rows = self._exec("SELECT * FROM conversations WHERE id=?", (cid,))
        return dict(rows[0]) if rows else None

    def list_conversations(self, project_id: str | None = None, limit: int = 200) -> list[dict]:
        """Chats of one project, or (project_id None) the chats outside every project."""
        where = "project_id=?" if project_id else "project_id IS NULL"
        params = (project_id, limit) if project_id else (limit,)
        return [dict(r) for r in self._exec(f"SELECT * FROM conversations WHERE {where} ORDER BY updated DESC LIMIT ?",
                                            params)]

    def update_conversation(self, cid: str, **fields: Any) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "mode", "provider_id"}}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE conversations SET {sets}, updated=? WHERE id=?", (*allowed.values(), time.time(), cid))
        return self.get_conversation(cid)

    def delete_conversation(self, cid: str) -> None:
        self._exec("DELETE FROM conversations WHERE id=?", (cid,))

    # -------------------------------------------------------------- messages
    def add_message(self, cid: str, role: str, content: str, meta: dict | None = None,
                    created: float | None = None) -> dict:
        """`created` is for imports: the message keeps its time and the chat's own `updated` is left alone."""
        mid, now = uuid.uuid4().hex, created or time.time()
        self._exec("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                   (mid, cid, role, content, json.dumps(meta or {}, ensure_ascii=False), now))
        if created is None:
            self._exec("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
        return {"id": mid, "conversation_id": cid, "role": role, "content": content, "meta": meta or {}, "created": now}

    def delete_messages_from(self, cid: str, mid: str) -> bool:
        """Delete one message and every later one of its chat (editing or retrying a turn); False if not found."""
        rows = self._exec("SELECT created FROM messages WHERE id=? AND conversation_id=?", (mid, cid))
        if not rows:
            return False
        self._exec("DELETE FROM messages WHERE conversation_id=? AND created>=?", (cid, rows[0]["created"]))
        return True

    def get_message(self, mid: str) -> dict | None:
        rows = self._exec("SELECT * FROM messages WHERE id=?", (mid,))
        return {**dict(rows[0]), "meta": json.loads(rows[0]["meta"])} if rows else None

    def update_message_meta(self, mid: str, meta: dict) -> None:
        self._exec("UPDATE messages SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), mid))

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

    # -------------------------------------------------------------- call log
    def log_call(self, provider_id: str, provider: str, status: str, model: str = "", local: bool = False,
                 tokens_in: int = 0, tokens_out: int = 0, estimated: bool = False, cost: float | None = None,
                 files_sent: int = 0, files_withheld: int = 0, detail: str = "") -> None:
        self._exec("INSERT INTO calls (ts, provider_id, provider, model, local, status, tokens_in, tokens_out, "
                   "estimated, cost, files_sent, files_withheld, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (time.time(), provider_id, provider, model, int(local), status, tokens_in, tokens_out,
                    int(estimated), cost, files_sent, files_withheld, detail))

    def calls(self, limit: int = 200, remote_only: bool = False) -> list[dict]:
        where = "WHERE local=0" if remote_only else ""
        rows = self._exec(f"SELECT * FROM calls {where} ORDER BY id DESC LIMIT ?", (limit,))
        return [{**dict(r), "local": bool(r["local"]), "estimated": bool(r["estimated"])} for r in rows]

    def usage_since(self, provider_id: str, since: float) -> dict[str, float]:
        row = self._exec("SELECT COUNT(*) AS calls, COALESCE(SUM(tokens_in),0) AS tokens_in, "
                         "COALESCE(SUM(tokens_out),0) AS tokens_out, COALESCE(SUM(cost),0) AS cost, "
                         "COALESCE(SUM(estimated),0) AS estimated FROM calls "
                         "WHERE provider_id=? AND ts>=? AND status!='blocked'", (provider_id, since))[0]
        return dict(row)

    def clear_calls(self) -> None:
        self._exec("DELETE FROM calls")

    # -------------------------------------------------------------- checkpoints (copies of files before a tool changed them)
    @staticmethod
    def _checkpoint(row: sqlite3.Row) -> dict:
        return {**dict(row), "files": json.loads(row["files"])}

    def save_checkpoint(self, cp: dict) -> None:
        self._exec("INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)",
                   (cp["id"], cp["conversation_id"], cp["call_id"], cp["tool"], cp["created"], cp["undone"],
                    json.dumps(cp["files"], ensure_ascii=False)))

    def get_checkpoint(self, cp_id: str) -> dict | None:
        rows = self._exec("SELECT * FROM checkpoints WHERE id=?", (cp_id,))
        return self._checkpoint(rows[0]) if rows else None

    def update_checkpoint(self, cp_id: str, **fields: Any) -> None:
        if "files" in fields:
            fields["files"] = json.dumps(fields["files"], ensure_ascii=False)
        allowed = {k: v for k, v in fields.items() if k in {"files", "undone"}}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE checkpoints SET {sets} WHERE id=?", (*allowed.values(), cp_id))

    def list_checkpoints(self, conversation_id: str) -> list[dict]:
        rows = self._exec("SELECT * FROM checkpoints WHERE conversation_id=? ORDER BY created", (conversation_id,))
        return [self._checkpoint(r) for r in rows]

    def stale_checkpoints(self, before: float) -> list[dict]:
        rows = self._exec("SELECT * FROM checkpoints WHERE created < ? OR conversation_id NOT IN "
                          "(SELECT id FROM conversations)", (before,))
        return [self._checkpoint(r) for r in rows]

    def delete_checkpoint(self, cp_id: str) -> None:
        self._exec("DELETE FROM checkpoints WHERE id=?", (cp_id,))

    def delete_checkpoints(self, conversation_id: str) -> None:
        self._exec("DELETE FROM checkpoints WHERE conversation_id=?", (conversation_id,))

    # -------------------------------------------------------------- projects
    def create_project(self, name: str, instructions: str = "", mode: str = "auto") -> dict:
        now, pid = time.time(), uuid.uuid4().hex
        self._exec("INSERT INTO projects VALUES (?,?,?,?,?,?)", (pid, name, instructions, mode, now, now))
        return self.get_project(pid)

    def get_project(self, pid: str) -> dict | None:
        rows = self._exec("SELECT * FROM projects WHERE id=?", (pid,))
        return dict(rows[0]) if rows else None

    def list_projects(self) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM projects ORDER BY updated DESC")]

    def update_project(self, pid: str, **fields: Any) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in PROJECT_FIELDS}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE projects SET {sets}, updated=? WHERE id=?", (*allowed.values(), time.time(), pid))
        return self.get_project(pid)

    def delete_project(self, pid: str) -> None:
        self._exec("DELETE FROM conversations WHERE project_id=?", (pid,))
        self._exec("DELETE FROM projects WHERE id=?", (pid,))
