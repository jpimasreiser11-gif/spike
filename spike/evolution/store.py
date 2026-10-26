"""What SPIKE keeps to learn from its own use, and every version of what that learning changed, in
$SPIKE_HOME/evolution.db. Nothing in it leaves the computer.

Items: `correction` (a rule saved from a correction, with the question and the answer it corrected), `route` (the
user retried an answer with another specialist), `failure` (a run or tool error, with the cause and fix the user
writes), `candidate` (a proposed eval question made from the others) and `example` (a correction as training
data, only when the user opted in) and `personal` (a chat marked for the personal adapter, or one item left out of it).
Versions: one row per change of a component (`router`, `strategy`, `adapter:<specialist>`, `adapter:personal`,
`prompt:<specialist>`); at most one is active, and rolling back activates the version it replaced (none active means
the built-in behaviour). Runs: one row per tool or skill a chat used, with the task type and whether it worked (EV3).
Only names, task types and flags are kept there, never the text of a chat."""

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
CREATE TABLE IF NOT EXISTS tool_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL, call TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
  name TEXT NOT NULL, task_type TEXT NOT NULL, ok INTEGER NOT NULL, flag TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_runs_by_message ON tool_runs(message);
CREATE INDEX IF NOT EXISTS tool_runs_by_key ON tool_runs(kind, name, task_type);
"""
KINDS = {"correction", "route", "failure", "candidate", "example", "personal"}
MAX_ITEMS = 2000  # per kind; the oldest are dropped first
MAX_RUNS = 20000  # tool and skill uses kept; the oldest are dropped first
RUN_FLAGS = ("retried", "undone", "corrected")  # why a use that returned fine still does not count as a success


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

    def activate(self, version_id: int) -> dict[str, Any]:
        """Make an existing version the active one of its component (a candidate that passed its check). What it
        replaces becomes the version active now, so a rollback goes back to it."""
        version = self.version(version_id)
        if version is None:
            raise LookupError(f"version {version_id} not found")
        current = self.active(version["component"])
        replaces = version["replaces"] if current and current["id"] == version_id else current["id"] if current else None
        with self._lock:
            self._conn.execute("UPDATE versions SET active = 0 WHERE component = ?", (version["component"],))
            self._conn.execute("UPDATE versions SET active = 1, replaces = ? WHERE id = ?", (replaces, version_id))
            self._conn.commit()
        return self.version(version_id)  # type: ignore[return-value]

    def deactivate(self, component: str) -> None:
        """Go back to the built-in behaviour without losing the versions (they stay in the history)."""
        self._exec("UPDATE versions SET active = 0 WHERE component = ?", (component,))

    def annotate(self, version_id: int, report: dict[str, Any] | None = None, reason: str | None = None) -> dict[str, Any]:
        """Add to a version's report (merged, key by key) and/or replace its reason: the result of a check."""
        version = self.version(version_id)
        if version is None:
            raise LookupError(f"version {version_id} not found")
        self._exec("UPDATE versions SET report = ?, reason = ? WHERE id = ?",
                   (json.dumps({**version["report"], **(report or {})}, ensure_ascii=False),
                    version["reason"] if reason is None else reason, version_id))
        return self.version(version_id)  # type: ignore[return-value]

    # -------------------------------------------------------------- tool and skill runs (EV3)
    def add_runs(self, rows: list[dict[str, Any]]) -> None:
        """Record uses of tools and skills: {message, call, kind, name, task_type, ok}."""
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO tool_runs (message, call, kind, name, task_type, ok, created) VALUES (?,?,?,?,?,?,?)",
                [(r["message"], r.get("call", ""), r["kind"], r["name"], r["task_type"], int(bool(r["ok"])), now)
                 for r in rows])
            self._conn.execute("DELETE FROM tool_runs WHERE id NOT IN (SELECT id FROM tool_runs ORDER BY id DESC "
                               "LIMIT ?)", (MAX_RUNS,))
            self._conn.commit()

    def flag_runs(self, messages: list[str], flag: str, call: str | None = None) -> int:
        """Mark the uses recorded for these answers as retried, undone or corrected (only the first reason is kept);
        `call` narrows it to one tool call. Returns how many uses changed."""
        if flag not in RUN_FLAGS:
            raise ValueError(f"unknown flag '{flag}'")
        if not messages:
            return 0
        marks = ",".join("?" * len(messages))
        sql = f"UPDATE tool_runs SET flag = ? WHERE flag = '' AND message IN ({marks})"
        params: list[Any] = [flag, *messages]
        if call is not None:
            sql, params = sql + " AND call = ?", [*params, call]
        with self._lock:
            changed = self._conn.execute(sql, params).rowcount
            self._conn.commit()
        return changed

    def run_stats(self) -> list[dict[str, Any]]:
        """Per (kind, name, task type): uses and successes. A success is a use that returned without an error and
        was not retried, undone or corrected afterwards."""
        rows = self._exec("SELECT kind, name, task_type, COUNT(*) AS n, SUM(ok = 1 AND flag = '') AS good, "
                          "SUM(flag = 'retried') AS retried, SUM(flag = 'undone') AS undone, "
                          "SUM(flag = 'corrected') AS corrected, MAX(created) AS last FROM tool_runs "
                          "GROUP BY kind, name, task_type ORDER BY kind, name, task_type")
        return [{"kind": r["kind"], "name": r["name"], "task_type": r["task_type"], "n": r["n"], "good": r["good"],
                 "retried": r["retried"], "undone": r["undone"], "corrected": r["corrected"], "last": r["last"]}
                for r in rows]

    def count_runs(self) -> int:
        return self._exec("SELECT COUNT(*) AS n FROM tool_runs")[0]["n"]

    def clear_runs(self) -> int:
        """Forget every recorded use (Settings → Evolución → reset); returns how many there were."""
        with self._lock:
            deleted = self._conn.execute("DELETE FROM tool_runs").rowcount
            self._conn.commit()
        return deleted
