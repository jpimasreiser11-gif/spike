"""Project forks reuse the portable project snapshot; merges require approval of a content-bound preview.

Only files are merged. Instructions and chats are forked once and subsequently independent. The base hashes flag
files changed on both sides. Approving a conflict explicitly chooses the branch's bytes (including deletions).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from spike.projects import (
    MAX_ARCHIVE_BYTES,
    ProjectError,
    ProjectFiles,
    clean_path,
    export_project,
    import_project,
)
from spike.store.db import Store


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ProjectBranches:
    def __init__(self, store: Store, files: ProjectFiles):
        self.store, self.files = store, files
        self.lock = threading.RLock()
        store._exec("CREATE TABLE IF NOT EXISTS project_branches (id TEXT PRIMARY KEY, parent TEXT, hashes TEXT)")

    def snapshot(self, pid: str) -> dict[str, bytes]:
        if not self.store.get_project(pid):
            raise ProjectError("project not found")
        project = self.files.root / pid
        base = project / "files"
        if project.is_symlink() or base.is_symlink() or not base.resolve().is_relative_to(self.files.root.resolve()):
            raise ProjectError("project contains symlinks")
        base = self.files.folder(pid)
        # No following symlinks, even a link to another project or a directory link with no regular children.
        if not base.resolve().is_relative_to(self.files.root.resolve()) or base.parent.is_symlink() or base.is_symlink() or any(p.is_symlink() for p in base.rglob("*")):
            raise ProjectError("project contains symlinks")
        items = self.files.list(pid)
        if sum(i["size"] for i in items) > MAX_ARCHIVE_BYTES:
            raise ProjectError("project too large")
        return {i["path"]: self.files.path(pid, i["path"]).read_bytes() for i in items}

    def fork(self, pid: str, name: str, modes: set[str]) -> dict[str, Any]:
        if not name.strip():
            raise ProjectError("branch needs a name")
        with self.lock:
            snapshot = self.snapshot(pid)
            project = import_project(self.store, self.files, export_project(self.store, self.files, pid), modes)
            self.store.update_project(project["id"], name=name.strip())
            hashes = {p: digest(b) for p, b in snapshot.items()}
            self.store._exec("INSERT INTO project_branches VALUES (?,?,?)",
                             (project["id"], pid, json.dumps(hashes)))
            return self.store.get_project(project["id"])

    def compare(self, bid: str) -> dict[str, Any]:
        rows = self.store._exec("SELECT * FROM project_branches WHERE id=?", (bid,))
        if not rows:
            raise ProjectError("project is not a branch")
        parent, base = rows[0]["parent"], json.loads(rows[0]["hashes"])
        source, target = self.snapshot(bid), self.snapshot(parent)
        changes = []
        for path in sorted(source.keys() | target.keys() | base.keys()):
            before, after = target.get(path), source.get(path)
            sh = digest(after) if after is not None else None
            th = digest(before) if before is not None else None
            if sh == th or sh == base.get(path):
                continue  # a parent-only change is preserved
            try:
                diff = "".join(difflib.unified_diff((before or b"").decode("utf-8").splitlines(keepends=True),
                                                   (after or b"").decode("utf-8").splitlines(keepends=True),
                                                   fromfile=f"parent/{path}", tofile=f"branch/{path}"))
            except UnicodeDecodeError:
                diff = ""  # byte counts and hashes identify a binary change without interpreting it
            changes.append({"path": path, "diff": diff, "before": th, "after": sh,
                            "before_size": len(before or b""), "after_size": len(after or b""),
                            "conflict": th != base.get(path), "deleted": after is None})
        # Include all bytes, even unchanged files, to reject any modification since the preview was approved.
        receipt = {"branch": bid, "parent": parent, "base": base,
                   "source": {p: digest(b) for p, b in source.items()},
                   "target": {p: digest(b) for p, b in target.items()}}
        return {"parent": parent, "files": changes,
                "token": digest(json.dumps(receipt, sort_keys=True).encode("utf-8"))}

    def merge(self, bid: str, token: str) -> dict[str, Any]:
        with self.lock:
            preview = self.compare(bid)
            if preview["token"] != token:
                raise RuntimeError("preview is stale; compare again")
            source = self.snapshot(bid)
            parent = preview["parent"]
            merged = self.snapshot(parent)
            for item in preview["files"]:
                if item["deleted"]:
                    merged.pop(item["path"], None)
                else:
                    merged[item["path"]] = source[item["path"]]
            if sum(len(b) for b in merged.values()) > MAX_ARCHIVE_BYTES:
                raise ProjectError("merged project too large")
            folder = self.files.folder(parent)
            with tempfile.TemporaryDirectory(prefix="merge-", dir=folder.parent) as temporary:
                staging = Path(temporary) / "files"
                backup = Path(temporary) / "backup"
                staging.mkdir()
                for path, data in merged.items():
                    target = staging.joinpath(*clean_path(path).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                os.replace(folder, backup)
                try:
                    os.replace(staging, folder)
                    self.store._exec("UPDATE project_branches SET hashes=? WHERE id=?",
                                     (json.dumps({p: digest(b) for p, b in source.items()}), bid))
                except BaseException:
                    if folder.exists():
                        shutil.rmtree(folder)
                    os.replace(backup, folder)
                    raise
            return {"ok": True, "files": len(preview["files"])}
