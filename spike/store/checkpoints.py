"""Copies of files taken just before a tool changes them, so each step of an answer can be undone."""

from __future__ import annotations

import hashlib
import shutil
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


class Checkpoints:
    def __init__(self, store: Store, root: Path):
        self.store = store
        self.root = root
        self.prune()

    def before(self, conversation_id: str, call_id: str, tool: str, paths: list[Path]) -> str | None:
        """Copy each target as it is now (or note that it does not exist yet); returns the checkpoint id."""
        if not paths:
            return None
        cid = uuid.uuid4().hex
        folder = self.root / cid
        files: list[dict[str, Any]] = []
        for i, path in enumerate(paths):
            entry: dict[str, Any] = {"path": str(path), "existed": path.is_file(), "before": None, "copy": None}
            if path.is_file():
                if path.stat().st_size > MAX_FILE_BYTES:
                    entry["too_big"] = True
                else:
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, folder / f"{i}.bin")
                    entry["copy"], entry["before"] = f"{i}.bin", _sha(path)
            files.append(entry)
        self.store.save_checkpoint({"id": cid, "conversation_id": conversation_id, "call_id": call_id, "tool": tool,
                                    "created": time.time(), "undone": None, "files": files})
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
        changed = [e["path"] for e in cp["files"] if _sha(Path(e["path"])) != e.get("after")]
        if changed and not force:
            raise CheckpointError(409, "these files changed after this step", changed)
        for entry in cp["files"]:
            path = Path(entry["path"])
            if entry["existed"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / checkpoint_id / entry["copy"], path)
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
