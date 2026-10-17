"""What SPIKE keeps to learn from its own use, and every version of what that learning changed, in
$SPIKE_HOME/evolution.db. Nothing in it leaves the computer.

Items: `correction` (a rule saved from a correction, with the question and the answer it corrected), `route` (the
user retried an answer with another specialist), `failure` (a run or tool error, with the cause and fix the user
writes) and `candidate` (a proposed eval question made from the others). Versions: one row per change of a
component (`router`, `adapter:<specialist>`); at most one is active, and rolling back activates the version it
replaced (none active means the built-in behaviour)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_by_kind ON items(kind, created);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, component TEXT NOT NULL, created REAL NOT NULL,
  active INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL, report TEXT NOT NULL DEFAULT '{}',
  reason TEXT NOT NULL DEFAULT '', replaces INTEGER
);
CREATE INDEX IF NOT EXISTS versions_by_component ON versions(component, id);
"""
KINDS = {"correction", "route", "failure", "candidate"}
MAX_ITEMS = 2000  # per kind; the oldest are dropped first


class EvolutionStore:
    def __init__(self, path: Path):
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            self._conn.commit()
            return rows

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "kind": row["kind"], "status": row["status"], "created": row["created"],
                "updated": row["updated"], **json.loads(row["data"])}

    # -------------------------------------------------------------- items
    def add(self, kind: str, data: dict[str, Any], status: str = "new") -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"unknown kind '{kind}'")
        iid, now = f"{kind[:3]}_{uuid.uuid4().hex[:12]}", time.time()
        self._exec("INSERT INTO items (id, kind, status, created, updated, data) VALUES (?,?,?,?,?,?)",
                   (iid, kind, status, now, now, json.dumps(data, ensure_ascii=False)))
        self._exec("DELETE FROM items WHERE kind = ? AND id NOT IN "
                   "(SELECT id FROM items WHERE kind = ? ORDER BY created DESC LIMIT ?)", (kind, kind, MAX_ITEMS))
        return self.get(iid)  # type: ignore[return-value]

    def get(self, item_id: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM items WHERE id = ?", (item_id,))
        return self._item(rows[0]) if rows else None

    def items(self, kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM items WHERE 1=1", []
        if kind:
            sql, params = sql + " AND kind = ?", [*params, kind]
        if status:
            sql, params = sql + " AND status = ?", [*params, status]
        return [self._item(r) for r in self._exec(sql + " ORDER BY created DESC", tuple(params))]

    def find(self, kind: str, **match: Any) -> dict[str, Any] | None:
        return next((it for it in self.items(kind) if all(it.get(k) == v for k, v in match.items())), None)

    def update(self, item_id: str, status: str | None = None, **data: Any) -> dict[str, Any] | None:
        current = self.get(item_id)
        if current is None:
            return None
        fields = {k: v for k, v in current.items() if k not in ("id", "kind", "status", "created", "updated")}
        fields.update(data)
        self._exec("UPDATE items SET status = ?, updated = ?, data = ? WHERE id = ?",
                   (status or current["status"], time.time(), json.dumps(fields, ensure_ascii=False), item_id))
        return self.get(item_id)

    def delete(self, item_id: str) -> bool:
        return bool(self._exec("DELETE FROM items WHERE id = ? RETURNING id", (item_id,)))

    # -------------------------------------------------------------- versions
    @staticmethod
    def _version(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "component": row["component"], "created": row["created"],
                "active": bool(row["active"]), "data": json.loads(row["data"]), "report": json.loads(row["report"]),
                "reason": row["reason"], "replaces": row["replaces"]}

    def add_version(self, component: str, data: dict[str, Any], report: dict[str, Any] | None = None,
                    reason: str = "", activate: bool = True) -> dict[str, Any]:
        current = self.active(component)
        with self._lock:
            if activate:
                self._conn.execute("UPDATE versions SET active = 0 WHERE component = ?", (component,))
            cur = self._conn.execute(
                "INSERT INTO versions (component, created, active, data, report, reason, replaces) "
                "VALUES (?,?,?,?,?,?,?)",
                (component, time.time(), int(activate), json.dumps(data, ensure_ascii=False),
                 json.dumps(report or {}, ensure_ascii=False), reason, current["id"] if current else None))
            self._conn.commit()
            vid = cur.lastrowid
        return self.version(vid)  # type: ignore[arg-type,return-value]

    def version(self, version_id: int) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM versions WHERE id = ?", (version_id,))
        return self._version(rows[0]) if rows else None

    def versions(self, component: str | None = None) -> list[dict[str, Any]]:
        if component:
            rows = self._exec("SELECT * FROM versions WHERE component = ? ORDER BY id DESC", (component,))
        else:
            rows = self._exec("SELECT * FROM versions ORDER BY id DESC")
        return [self._version(r) for r in rows]

    def active(self, component: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM versions WHERE component = ? AND active = 1", (component,))
        return self._version(rows[0]) if rows else None

    def rollback(self, component: str) -> dict[str, Any] | None:
        """Activate the version the active one replaced; None when that is the built-in behaviour."""
        current = self.active(component)
        if current is None:
            raise LookupError(f"'{component}' already uses the built-in version")
        with self._lock:
            self._conn.execute("UPDATE versions SET active = 0 WHERE component = ?", (component,))
            if current["replaces"]:
                self._conn.execute("UPDATE versions SET active = 1 WHERE id = ?", (current["replaces"],))
            self._conn.commit()
        return self.version(current["replaces"]) if current["replaces"] else None
