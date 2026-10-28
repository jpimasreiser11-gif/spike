"""Read saved Dev sessions without creating application state, contacting providers or migrating the database.

The folder is matched before paging; a busy unrelated project cannot hide the last conversation. Existing native
Windows title paths are accepted alongside portable paths. IDs are exact, never prefixes or paths supplied by a model.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def session_titles(root: Path) -> tuple[str, str]:
    root = root.resolve()
    return f"dev:{root.as_posix()}", f"dev:{root}"


def _query(path: Path, sql: str, params: tuple) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    # mode=ro retains WAL visibility; immutable would hide an active session's uncheckpointed messages.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def list_sessions(path: Path, root: Path, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """One page, newest first; only the first user request is previewed (120 characters, no assistant output)."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1–100 and offset must be non-negative / límite 1–100 y desplazamiento >= 0")
    return _query(path, """SELECT c.id, c.updated, c.mode, c.provider_id,
        (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS messages,
        COALESCE((SELECT SUBSTR(m.content,1,120) FROM messages m
                  WHERE m.conversation_id=c.id AND m.role='user' ORDER BY m.created, m.rowid LIMIT 1), '') AS preview
        FROM conversations c WHERE c.title IN (?,?) AND c.project_id IS NULL
        ORDER BY c.updated DESC, c.id DESC LIMIT ? OFFSET ?""", (*session_titles(root), limit, offset))


def find_session(path: Path, root: Path, session_id: str | None = None) -> dict[str, Any] | None:
    """Find an exact ID in this folder, or its latest conversation; never create one when an ID is missing."""
    where = " AND id=?" if session_id is not None else ""
    params = (*session_titles(root), session_id) if session_id is not None else session_titles(root)
    rows = _query(path, f"SELECT * FROM conversations WHERE title IN (?,?) AND project_id IS NULL{where} "
                       "ORDER BY updated DESC, id DESC LIMIT 1", params)
    return rows[0] if rows else None
