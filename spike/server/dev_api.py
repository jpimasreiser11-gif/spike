"""O1: Dev sessions in the app. The same `DevSession` as `spike dev` (one engine) behind HTTP: open a session on a folder
the user names, send turns streamed as server-sent events, plan / act modes, skills per turn, the list of changes with
undo, cancel and close. Every route works only from this computer's browser.

What the user must answer (a permission to edit or run, a question from `ask_user`) is streamed as the same
`permission_request` / `question` events as in the chat and waits for the user: `DevSession` is given the `WAIT`
answer, so nothing is resolved until `POST /api/dev/permissions/{id}` or `/api/dev/questions/{id}` arrives. The
session is never started with edits pre-approved. A request that is cancelled, or whose browser tab closes, stops the
turn and the command it was running (`run_command` kills its process group when its task is cancelled).

Sessions live in memory, one per folder; the saved conversation and the checkpoints are the DevSession's own database,
so a restart opens no session and runs nothing: resuming shows the history and the changes that can still be undone.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from spike.dev.history import find_session, list_sessions
from spike.dev.session import WAIT, DevSession
from spike.store.checkpoints import CheckpointError
from spike.tools.builtin import Workspace

KEEPALIVE_S = 15.0  # a comment line while a permission card waits, so nothing in between closes the stream


class OpenIn(BaseModel):
    folder: str = Field(max_length=4096)
    confirm_broad: bool = False  # the home folder or a disk root, confirmed by the user in the UI
    resume: bool = False  # the latest saved conversation of this folder
    resume_id: str | None = Field(default=None, max_length=80)
    plan: bool | None = None
    specialist: str = Field(default="code", max_length=40)
    provider_id: str | None = Field(default=None, max_length=80)


class TurnIn(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    skills: list[str] = Field(default_factory=list, max_length=3)


class ModeIn(BaseModel):
    plan: bool


class UndoIn(BaseModel):
    force: bool = False


class DecisionIn(BaseModel):
    decision: Literal["allow_once", "allow_always", "deny"]


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)


@dataclass
class Active:
    id: str
    session: DevSession
    broad: bool
    task: asyncio.Task | None = None
    started: float = 0.0
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()


def sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


def create_dev_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    def local(request: Request) -> None:
        this_computer(request, "Dev sessions")

    router = APIRouter(prefix="/api/dev", dependencies=[Depends(local)])
    sessions: dict[str, Active] = {}

    def key(root: Path) -> str:
        return os.path.normcase(str(root))

    def check_folder(raw: str, *, confirm_broad: bool) -> tuple[Path, bool]:
        """The folder the user chose, resolved; the same warning as the terminal for the home folder and a disk
        root, which here needs an explicit confirmation. SPIKE's own data folder is never offered to a model."""
        raw = (raw or "").strip()
        if not raw or not (raw.startswith("~") or Path(raw).is_absolute()):
            raise HTTPException(400, "dev_folder_relative")
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            raise HTTPException(400, "dev_folder_missing")
        if not root.is_dir():
            raise HTTPException(400, "dev_folder_not_dir")
        data = get_state().home.resolve()
        if root == data or data in root.parents:
            raise HTTPException(403, "dev_folder_forbidden")
        broad = root in (Path.home().resolve(), Path(root.anchor))
        if broad and not confirm_broad:
            raise HTTPException(409, "dev_folder_broad")
        return root, broad

    def find(session_id: str) -> Active:
        active = sessions.get(session_id)
        if active is None:
            raise HTTPException(404, "dev_session_unknown")
        return active

    def idle(session_id: str) -> Active:
        active = find(session_id)
        if active.running:
            raise HTTPException(409, "dev_turn_running")
        return active

    def summary(active: Active) -> dict[str, Any]:
        s = active.session
        try:
            provider, model = s.backend()
        except Exception:  # noqa: BLE001 - no provider yet: the first turn explains it
            provider, model = "", ""
        iso = s.state.sandbox.isolation(command=True)
        return {"id": active.id, "folder": str(s.root), "conversation_id": s.conversation_id, "plan": s.plan_mode,
                "running": active.running, "specialist": s.specialist, "provider": provider, "model": model,
                "history": len(s.history), "broad": active.broad,
                "sandbox": iso.line(), "isolation": iso.to_dict()}  # the app translates `isolation` by its code

    async def stop(active: Active) -> bool:
        """Cancel the running turn and wait until it has ended (its command is killed on the way)."""
        task = active.task
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.wait({task}, timeout=10)
        return True

    # ------------------------------------------------------------------ sessions
    @router.get("/sessions")
    async def list_active() -> dict:
        return {"active": [summary(a) for a in sessions.values()]}

    @router.get("/history")
    async def history(folder: str = Query(max_length=4096), limit: int = Query(20, ge=1, le=100),
                      offset: int = Query(0, ge=0)) -> dict:
        """Saved conversations of one folder, newest first (read-only: nothing is opened or run)."""
        root, _ = check_folder(folder, confirm_broad=True)
        try:
            rows = list_sessions(get_state().home / "dev" / "sessions.db", root, limit=limit, offset=offset)
        except (sqlite3.Error, OSError) as exc:
            raise HTTPException(500, "dev_history_unreadable") from exc
        open_here = next((a.id for a in sessions.values() if key(a.session.root) == key(root)), None)
        return {"folder": str(root), "sessions": rows, "active": open_here}

    @router.post("/sessions")
    async def open_session(body: OpenIn) -> dict:
        state = get_state()
        root, broad = check_folder(body.folder, confirm_broad=body.confirm_broad)
        if any(key(a.session.root) == key(root) for a in sessions.values()):
            raise HTTPException(409, "dev_session_open")
        if body.provider_id and not state.provider_config(body.provider_id):
            raise HTTPException(400, "dev_provider_unknown")
        if body.resume and body.resume_id is not None:
            raise HTTPException(400, "dev_resume_both")
        path = state.home / "dev" / "sessions.db"
        try:
            if body.resume_id is not None and find_session(path, root, body.resume_id) is None:
                raise HTTPException(404, "dev_resume_unknown")
            session = DevSession(state, root, provider_id=body.provider_id, specialist=body.specialist,
                                 resume=body.resume, resume_id=body.resume_id, plan=body.plan,
                                 decide=lambda ev: WAIT, answer=lambda ev: WAIT)  # never accept_edits: edits ask
        except KeyError as exc:
            raise HTTPException(400, "dev_specialist_unknown") from exc
        except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(400, str(exc)) from exc
        active = Active(id=f"dev_{uuid.uuid4().hex[:12]}", session=session, broad=broad)
        sessions[active.id] = active
        return summary(active)

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        return summary(find(session_id))

    @router.delete("/sessions/{session_id}")
    async def close_session(session_id: str) -> dict:
        active = find(session_id)
        await stop(active)
        sessions.pop(session_id, None)
        active.session.close()
        return {"ok": True}

    @router.get("/sessions/{session_id}/messages")
    async def messages(session_id: str) -> dict:
        s = find(session_id).session
        return {"conversation_id": s.conversation_id, "messages": [
            {"id": m["id"], "role": m["role"], "content": m["content"], "meta": m["meta"], "created": m["created"]}
            for m in s.store.messages(s.conversation_id) if m["role"] in ("user", "assistant")]}

    @router.post("/sessions/{session_id}/mode")
    async def set_mode(session_id: str, body: ModeIn) -> dict:
        active = idle(session_id)
        active.session.plan_mode = body.plan  # leaving the plan sends and runs nothing; the next request does
        return {"plan": active.session.plan_mode}

    @router.post("/sessions/{session_id}/clear")
    async def clear(session_id: str) -> dict:
        active = idle(session_id)
        active.session.clear()
        return {"conversation_id": active.session.conversation_id}

    # ------------------------------------------------------------------ turns
    @router.post("/sessions/{session_id}/turn")
    async def turn(session_id: str, body: TurnIn) -> StreamingResponse:
        active = idle(session_id)
        try:
            skills = active.session.check_skills(body.skills)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        queue: asyncio.Queue = asyncio.Queue()

        async def work() -> None:
            try:
                async for ev in active.session.turn(body.message, skills=skills):
                    queue.put_nowait(ev)
            except asyncio.CancelledError:
                queue.put_nowait({"type": "stopped"})
                raise
            except Exception as exc:  # noqa: BLE001 - the browser always learns why the turn ended
                queue.put_nowait({"type": "error", "message": f"{exc.__class__.__name__}: {exc}"})
            finally:
                queue.put_nowait(None)

        task = asyncio.get_running_loop().create_task(work())
        active.task = task

        async def stream() -> AsyncIterator[bytes]:
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                    except TimeoutError:
                        yield b": waiting\n\n"
                        continue
                    if ev is None:
                        return
                    yield sse(ev)
            finally:
                if not task.done():  # the browser left: the turn stops, as Ctrl-C does in the terminal
                    task.cancel()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/sessions/{session_id}/cancel")
    async def cancel(session_id: str) -> dict:
        return {"cancelled": await stop(find(session_id))}

    # ------------------------------------------------------------------ answers to the cards
    @router.post("/permissions/{request_id}")
    async def decide(request_id: str, body: DecisionIn) -> dict:
        for active in sessions.values():
            if request_id in active.session.broker.pending and \
                    active.session.broker.resolve(request_id, body.decision):
                return {"ok": True}
        raise HTTPException(404, "no pending permission request with this id")

    @router.post("/questions/{question_id}")
    async def answer(question_id: str, body: AnswerIn) -> dict:
        for active in sessions.values():
            if question_id in active.session.broker.questions and \
                    active.session.broker.answer(question_id, body.answer.strip()):
                return {"ok": True}
        raise HTTPException(404, "no pending question with this id")

    # ------------------------------------------------------------------ changes and undo
    def change_rows(s: DevSession) -> list[dict[str, Any]]:
        return [{"id": c["id"], "tool": c["tool"], "created": c["created"], "undone": bool(c["undone"]),
                 "files": [s.relative(f["path"]) for f in c["files"]]} for c in s.changes()]

    @router.get("/sessions/{session_id}/changes")
    async def changes(session_id: str) -> dict:
        return {"changes": change_rows(find(session_id).session)}

    @router.post("/sessions/{session_id}/undo", response_model=None)
    async def undo(session_id: str, body: UndoIn) -> dict | JSONResponse:
        """Put back the files of the latest change not undone yet; files that changed since need `force`."""
        s = idle(session_id).session
        try:
            cp = s.undo_last(force=body.force)
        except CheckpointError as exc:
            if exc.status == 409:
                return JSONResponse({"detail": "dev_undo_conflict", "changed": [s.relative(p) for p in exc.changed]},
                                    status_code=409)
            raise HTTPException(exc.status, "dev_nothing_to_undo" if str(exc) == "nothing to undo" else str(exc)) \
                from exc
        return {"id": cp["id"], "tool": cp["tool"], "files": [s.relative(f["path"]) for f in cp["files"]]}

    # ------------------------------------------------------------------ files and skills
    @router.get("/sessions/{session_id}/files/{path:path}")
    async def get_file(session_id: str, path: str) -> FileResponse:
        """A file of the session's folder as a download (the list of files a turn made, with preview)."""
        try:
            target = Workspace(find(session_id).session.root).resolve(path)
        except PermissionError as exc:
            raise HTTPException(400, "the path is outside the folder") from exc
        if not target.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(target, filename=target.name, content_disposition_type="attachment",
                            headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/skills")
    async def skills() -> dict:
        state = get_state()
        settings = state.settings()
        return {"skill_mode": settings["skill_mode"], "skills": [
            {"name": s.name, "description": s.description, "source": s.source,
             "enabled": settings["skill_mode"] != "off" and s.name not in settings["disabled_skills"]}
            for s in state.skills.all()]}

    return router
