"""Local immutable artifact versions and line-anchored discussions; model context is opt-in per request."""

from __future__ import annotations

import time
import uuid

from spike.project_branches import digest
from spike.store.db import Store


class ArtifactComments:
    def __init__(self, store: Store):
        self.store = store
        store._exec("CREATE TABLE IF NOT EXISTS artifact_versions (id TEXT PRIMARY KEY, title TEXT, content TEXT)")
        store._exec("CREATE TABLE IF NOT EXISTS artifact_comments "
                    "(id TEXT PRIMARY KEY, version TEXT, line INTEGER, text TEXT, parent TEXT, created REAL)")

    def version(self, title: str, content: str) -> dict:
        aid = digest(content.encode("utf-8"))
        self.store._exec("INSERT OR IGNORE INTO artifact_versions VALUES (?,?,?)", (aid, title, content))
        return {"id": aid}

    def comments(self, aid: str) -> list[dict]:
        return [dict(r) for r in self.store._exec("SELECT * FROM artifact_comments WHERE version=? ORDER BY created",
                                               (aid,))]

    def add(self, aid: str, line: int, text: str, parent: str | None = None) -> dict:
        versions = self.store._exec("SELECT content FROM artifact_versions WHERE id=?", (aid,))
        if not versions or not 1 <= line <= len(versions[0]["content"].splitlines()):
            raise ValueError("unknown version or invalid line")
        if not text.strip():
            raise ValueError("comment needs text")
        if parent and not any(c["id"] == parent and c["parent"] is None and c["line"] == line
                              for c in self.comments(aid)):
            raise ValueError("reply must use the root thread's version and line")
        cid = uuid.uuid4().hex
        self.store._exec("INSERT INTO artifact_comments VALUES (?,?,?,?,?,?)",
                         (cid, aid, line, text.strip(), parent, time.time()))
        return next(c for c in self.comments(aid) if c["id"] == cid)

    def context(self, threads: list[str]) -> str:
        blocks = []
        for tid in dict.fromkeys(threads):
            rows = self.store._exec("SELECT c.*, v.title, v.content FROM artifact_comments c "
                                    "JOIN artifact_versions v ON v.id=c.version WHERE c.id=? AND c.parent IS NULL", (tid,))
            if not rows:
                raise ValueError("unknown comment thread")
            row = rows[0]
            comments = [c["text"] for c in self.comments(row["version"]) if c["id"] == tid or c["parent"] == tid]
            blocks.append(f"Artifact {row['title']} version {row['version']} line {row['line']}:\n"
                          + row["content"].splitlines()[row["line"] - 1] + "\n" + "\n".join(comments))
        return "\n\n".join(blocks)[:20000]
