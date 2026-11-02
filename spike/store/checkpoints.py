"""Copies of files taken just before a tool changes them, so each step of an answer can be undone."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from spike.store.db import Store

MAX_FILE_BYTES = 100 * 1024 * 1024  # bigger files are changed without a copy, and that step cannot be undone
KEEP_DAYS = 30


class CheckpointError(Exception):
    def __init__(self, status: int, message: str, changed: list[str] | None = None):
        super().__init__(message)
        self.status, self.changed = status, changed or []


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        norm = os.path.abspath(raw)
        if norm not in seen:
            seen.add(norm)
            unique.append(Path(norm))
    return unique


def _expected_sha(entry: dict[str, Any]) -> str | None:
    if "after" in entry:
        return entry["after"]
    return entry.get("before") if entry.get("existed") else None


def _path_blocked(path: Path) -> bool:
    if (path.exists() or path.is_symlink()) and not path.is_file():
        return True
    return any((anc.exists() or anc.is_symlink()) and not anc.is_dir() for anc in path.parents)


def _atomic_restore(backup: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".spike-undo-", dir=target.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(backup, tmp_path)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


class Checkpoints:
    def __init__(self, store: Store, root: Path):
        self.store = store
        self.root = root
        self.prune()

    def before(self, conversation_id: str, call_id: str, tool: str, paths: list[Path]) -> str | None:
        """Copy each target as it is now (or note that it does not exist yet); returns the checkpoint id."""
        unique = _dedupe_paths(paths)
        if not unique:
            return None
        cid = uuid.uuid4().hex
        folder = self.root / cid
        files: list[dict[str, Any]] = []
        try:
            for i, path in enumerate(unique):
                existed = path.is_file()
                entry: dict[str, Any] = {"path": str(path), "existed": existed, "before": None, "copy": None}
                if existed:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        entry["too_big"] = True
                    else:
                        folder.mkdir(parents=True, exist_ok=True)
                        backup = folder / f"{i}.bin"
                        shutil.copy2(path, backup)
                        entry["copy"], entry["before"] = f"{i}.bin", _sha(backup)
                files.append(entry)
            self.store.save_checkpoint({"id": cid, "conversation_id": conversation_id, "call_id": call_id, "tool": tool,
                                        "created": time.time(), "undone": None, "files": files})
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return cid

    def after(self, checkpoint_id: str) -> None:
        cp = self.store.get_checkpoint(checkpoint_id)
        if cp is None:
            return
        for entry in cp["files"]:
            entry["after"] = _sha(Path(entry["path"]))
        self.store.update_checkpoint(checkpoint_id, files=cp["files"])

    def undo(self, checkpoint_id: str, force: bool = False) -> dict[str, Any]:
        """Put the files back as they were before the step. A file changed again since then is only overwritten
        with `force`, so later work is never lost by accident."""
        cp = self.store.get_checkpoint(checkpoint_id)
        if cp is None:
            raise CheckpointError(404, "checkpoint not found")
        if cp["undone"]:
            raise CheckpointError(400, "this step was already undone")
        if any(e.get("too_big") for e in cp["files"]):
            raise CheckpointError(400, "a file was too big to keep a copy of, so this step cannot be undone")
        folder = self.root / checkpoint_id
        backups: dict[str, Path] = {}
        for entry in cp["files"]:
            if entry.get("existed"):
                copy_name = entry.get("copy")
                if (not isinstance(copy_name, str) or "/" in copy_name or "\\" in copy_name
                        or copy_name in ("", ".", "..")):
                    raise CheckpointError(400, "checkpoint backup copy is missing or invalid")
                backup = folder / copy_name
                if not backup.is_file() or not isinstance(entry.get("before"), str) or _sha(backup) != entry["before"]:
                    raise CheckpointError(400, "checkpoint backup copy is missing or corrupted")
                backups[entry["path"]] = backup
        blocked = [e["path"] for e in cp["files"] if _path_blocked(Path(e["path"]))]
        if blocked:
            raise CheckpointError(409, "a directory or file blocks restoring these paths", blocked)
        changed = [e["path"] for e in cp["files"] if _sha(Path(e["path"])) != _expected_sha(e)]
        if changed and not force:
            raise CheckpointError(409, "these files changed after this step", changed)
        for entry in cp["files"]:
            path = Path(entry["path"])
            if entry.get("existed"):
                _atomic_restore(backups[entry["path"]], path)
            elif path.is_file():
                path.unlink()
        self.store.update_checkpoint(checkpoint_id, undone=time.time())
        return {**cp, "undone": True}

    def delete_conversation(self, conversation_id: str) -> None:
        for cp in self.store.list_checkpoints(conversation_id):
            shutil.rmtree(self.root / cp["id"], ignore_errors=True)
        self.store.delete_checkpoints(conversation_id)

    def prune(self, days: int = KEEP_DAYS) -> None:
        """Forget copies older than `days` and those of deleted chats."""
        for cp in self.store.stale_checkpoints(time.time() - days * 86400):
            shutil.rmtree(self.root / cp["id"], ignore_errors=True)
            self.store.delete_checkpoint(cp["id"])


class RunCheckpoints:
    """The checkpoints of one chat, handed to the agent loop for the length of a run."""

    def __init__(self, checkpoints: Checkpoints, conversation_id: str):
        self.checkpoints, self.conversation_id = checkpoints, conversation_id

    def before(self, call_id: str, tool: str, paths: list[Path]) -> str | None:
        return self.checkpoints.before(self.conversation_id, call_id, tool, paths)

    def after(self, checkpoint_id: str) -> None:
        self.checkpoints.after(checkpoint_id)
