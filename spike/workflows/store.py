"""Where workflows live: JSON files in the project's own folder, so they travel with the project (export, import,
branches, deletion) like any other file of it.

    workflows/<id>/<NNNN>.json      one file per saved version, never changed afterwards; the newest is the workflow
    workflows/<id>/runs/<run>.json  the record of each run (inputs, per-node output or error, timings)

Without a project the same layout is used inside the workspace folder. Files are read as untrusted: size-capped,
parsed with `clean`, and a bad one is reported, never trusted.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from spike.workflows.model import Environment, Problem, WorkflowError, clean, validate

FOLDER = "workflows"
MAX_BYTES = 1024**2  # a workflow or a run record file
MAX_VERSIONS = 50  # the newest are kept
MAX_RUNS = 50
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
RUN_ID = re.compile(r"[0-9]{13}-[0-9a-f]{6}")


class WorkflowInvalid(WorkflowError):
    """A workflow that did not pass `validate`; `problems` says why, node by node."""

    def __init__(self, problems: list[Problem]):
        super().__init__("; ".join(p.message for p in problems[:3]), problems)


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowConflict(WorkflowError):
    """The workflow was saved by someone else since `base_revision`."""


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


def _read(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise WorkflowError("the file is missing, linked or too large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise WorkflowError("the file is not valid JSON") from exc


class WorkflowStore:
    """The workflows of one folder (a project's files, or the workspace)."""

    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------------ paths
    def _base(self) -> Path:
        base = self.root / FOLDER
        if base.is_symlink():
            raise WorkflowError("the workflows folder is a link")
        return base

    def _dir(self, wid: str) -> Path:
        if not ID.fullmatch(wid):
            raise WorkflowNotFound("unknown workflow")
        folder = self._base() / wid
        if folder.is_symlink():
            raise WorkflowError("the workflow folder is a link")
        return folder

    def _versions(self, wid: str) -> list[int]:
        folder = self._dir(wid)
        if not folder.is_dir():
            return []
        return sorted(int(p.stem) for p in folder.glob("[0-9][0-9][0-9][0-9].json") if p.is_file())

    # ------------------------------------------------------------------ workflows
    def list(self) -> list[dict[str, Any]]:
        """Every workflow's newest version, summarised; a folder that does not read shows as `broken`."""
        base = self._base()
        out = []
        for folder in sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []:
            if not ID.fullmatch(folder.name):
                continue
            try:
                doc = self.get(folder.name)
            except WorkflowError:
                out.append({"id": folder.name, "name": folder.name, "broken": True})
                continue
            out.append({"id": doc["id"], "name": doc["name"], "revision": doc["revision"], "saved": doc["saved"],
                        "nodes": len(doc["nodes"])})
        return sorted(out, key=lambda w: (-w.get("saved", 0), w["id"]))

    def get(self, wid: str, revision: int | None = None) -> dict[str, Any]:
        versions = self._versions(wid)
        if not versions or (revision is not None and revision not in versions):
            raise WorkflowNotFound("unknown workflow or version")
        number = revision if revision is not None else versions[-1]
        raw = _read(self._dir(wid) / f"{number:04d}.json")
        doc = clean(raw)
        meta = raw if isinstance(raw, dict) else {}
        saved = meta.get("saved")
        return {**doc, "id": wid, "revision": number,
                "saved": saved if isinstance(saved, int | float) and not isinstance(saved, bool) else 0}

    def versions(self, wid: str) -> list[dict[str, Any]]:
        out = []
        for number in reversed(self._versions(wid)):
            try:
                doc = self.get(wid, number)
            except WorkflowError:
                continue
            out.append({"revision": number, "saved": doc["saved"], "name": doc["name"], "nodes": len(doc["nodes"])})
        return out

    def save(self, raw: Any, env: Environment, wid: str | None = None, base_revision: int | None = None) -> dict[str, Any]:
        """Check the workflow and write it as the next version of `wid` (a new workflow when None). Raises
        WorkflowInvalid with every problem when it does not pass, and WorkflowConflict when `base_revision` is not
        the newest version any more."""
        doc = clean(raw)
        if not doc["name"]:
            raise WorkflowInvalid([Problem("name", "the workflow needs a name")])
        if problems := validate(doc, env):
            raise WorkflowInvalid(problems)
        wid = wid or f"wf-{uuid.uuid4().hex[:10]}"
        versions = self._versions(wid)
        if base_revision is not None and base_revision != (versions[-1] if versions else 0):
            raise WorkflowConflict("the workflow was saved again since you opened it")
        number = (versions[-1] if versions else 0) + 1
        if number > 9999:
            raise WorkflowError("too many versions")
        saved = {**doc, "id": wid, "revision": number, "saved": round(time.time(), 3)}
        folder = self._dir(wid)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with open(folder / f"{number:04d}.json", "x", encoding="utf-8") as f:
                f.write(_dump(saved))
        except FileExistsError as exc:
            raise WorkflowConflict("the workflow was saved again since you opened it") from exc
        for old in versions[:max(0, len(versions) + 1 - MAX_VERSIONS)]:
            (folder / f"{old:04d}.json").unlink(missing_ok=True)
        return saved

    def delete(self, wid: str) -> None:
        folder = self._dir(wid)
        if not folder.is_dir():
            raise WorkflowNotFound("unknown workflow")
        shutil.rmtree(folder)

    @staticmethod
    def export(doc: dict[str, Any]) -> dict[str, Any]:
        """The portable form: the document without the id and revision of this folder."""
        return {k: v for k, v in doc.items() if k not in ("id", "revision", "saved")}

    # ------------------------------------------------------------------ runs
    def _runs(self, wid: str) -> Path:
        return self._dir(wid) / "runs"

    def save_run(self, wid: str, record: dict[str, Any]) -> None:
        """Write (or rewrite) a run's record, keeping the newest MAX_RUNS."""
        if not RUN_ID.fullmatch(record["id"]):
            raise WorkflowError("invalid run id")
        folder = self._runs(wid)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{record['id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(_dump(record), encoding="utf-8")
        os.replace(temporary, target)
        for old in sorted(p for p in folder.glob("*.json"))[:-MAX_RUNS]:
            old.unlink(missing_ok=True)

    def get_run(self, wid: str, rid: str) -> dict[str, Any]:
        if not RUN_ID.fullmatch(rid):
            raise WorkflowNotFound("unknown run")
        path = self._runs(wid) / f"{rid}.json"
        if not path.is_file():
            raise WorkflowNotFound("unknown run")
        record = _read(path)
        if not isinstance(record, dict) or record.get("id") != rid:
            raise WorkflowError("the run record is not valid")
        return record

    def list_runs(self, wid: str, limit: int = 30) -> list[dict[str, Any]]:
        """The newest runs, summarised (newest first)."""
        folder = self._runs(wid)
        out = []
        for path in sorted(folder.glob("*.json"), reverse=True)[:limit] if folder.is_dir() else []:
            try:
                out.append(summary(self.get_run(wid, path.stem)))
            except WorkflowError:
                continue
        return out


def summary(record: dict[str, Any]) -> dict[str, Any]:
    return {k: record.get(k) for k in ("id", "status", "started", "finished", "elapsed_s", "workflow_revision")} | {
        "nodes": {nid: n.get("status") for nid, n in (record.get("nodes") or {}).items()}}
