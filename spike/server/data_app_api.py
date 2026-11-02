"""Creator's deterministic data app: process-local, bounded sessions and one-use review receipts.

The opaque artifact can propose cell edits only. Approval belongs to the host UI; the iframe has no API access.
Restarting the server expires sessions. Generated HTML remains a standalone, offline query/edit draft.
"""

from __future__ import annotations

import re
import time
import uuid
import zipfile
from collections.abc import Callable
from typing import Any
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spike import data_app
from spike.runtime.paths import workspace_dir


class LabelsIn(BaseModel):
    search: str = Field(max_length=100)
    propose: str = Field(max_length=100)
    hint: str = Field(max_length=300)


class CreateIn(BaseModel):
    file: str = Field(max_length=600)
    project_id: str | None = None
    lang: str = "es"
    title: str = Field(default="", max_length=600)
    approved: bool = False
    labels: LabelsIn | None = None


class EditIn(BaseModel):
    row: int
    column: int
    value: str = Field(max_length=2000)


class PreviewIn(BaseModel):
    edits: list[EditIn] = Field(min_length=1, max_length=500)


class ApproveIn(BaseModel):
    token: str
    approved: bool = False


def create_data_app_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/creator/data-app")
    sessions: dict[str, dict] = {}

    def session(sid: str) -> dict:
        item = sessions.get(sid)
        if item is None or time.monotonic() - item["created"] > 3600:
            sessions.pop(sid, None)
            raise HTTPException(409, "data_app_expired")
        return item

    def source(item: dict):
        path = data_app.safe_path(item["root"], item["file"])
        if data_app.digest(path) != item["hash"]:
            raise HTTPException(409, "data_app_conflict")
        return path

    @router.post("")
    async def create(body: CreateIn) -> dict:
        if not body.approved:
            raise HTTPException(403, "data_app_approval")
        state = get_state()
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(404, "data_app_project")
        try:
            root = state.project_files.folder(body.project_id) if body.project_id else workspace_dir()
            root = root.resolve()
            path = data_app.safe_path(root, body.file)
            fingerprint = data_app.digest(path)
            rows = data_app.table(path)
            if data_app.digest(path) != fingerprint:
                raise ValueError("data_app_conflict")
            labels = [body.labels.search, body.labels.propose, body.labels.hint] if body.labels else None
            html = data_app.document(rows, body.lang, body.title or body.file, labels)
            sid = uuid.uuid4().hex
            relative = f"data-app-{sid}/app.html"
            target = data_app.safe_path(root, relative)
            target.parent.mkdir()
            target.write_text(html, encoding="utf-8")
            for key in list(sessions):
                if time.monotonic() - sessions[key]["created"] > 3600:
                    sessions.pop(key)
            if len(sessions) >= 32:
                sessions.pop(next(iter(sessions)))
            sessions[sid] = {"root": root, "file": body.file, "hash": fingerprint, "rows": rows,
                             "created": time.monotonic(), "pending": None}
            return {"id": sid, "html": html, "path": relative, "filename": "app.html", "title": body.title or body.file}
        except (ValueError, OSError, zipfile.BadZipFile, ParseError, KeyError) as exc:
            # Parser failures have no source text or local paths in the response.
            raise HTTPException(400, "data_app_invalid") from exc

    @router.post("/{sid}/preview")
    async def preview(sid: str, body: PreviewIn) -> dict:
        item = session(sid)
        try:
            source(item)
            changes, seen = [], set()
            rows = item["rows"]
            for edit in body.edits:
                key = (edit.row, edit.column)
                if (key in seen or not 0 <= edit.row < len(rows) - 1 or not 0 <= edit.column < len(rows[0])
                        or (edit.value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                            and not re.fullmatch(r"-\d+(?:\.\d+)?", edit.value))):
                    raise ValueError("invalid edit")
                seen.add(key)
                before = rows[edit.row + 1][edit.column]
                if before != edit.value:
                    changes.append({"row": edit.row, "column": edit.column, "before": before, "after": edit.value})
            token = uuid.uuid4().hex
            item["pending"] = {"token": token, "changes": changes}
            return item["pending"]
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "data_app_invalid") from exc

    @router.post("/{sid}/approve")
    async def approve(sid: str, body: ApproveIn) -> dict:
        if not body.approved:
            raise HTTPException(403, "data_app_approval")
        item = session(sid)
        pending = item["pending"]
        if not pending or pending["token"] != body.token:
            raise HTTPException(409, "data_app_expired")
        try:
            path = source(item)
            data_app.write_edits(path, pending["changes"])
            sessions.pop(sid)
            return {"saved": True}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "data_app_invalid") from exc

    return router
