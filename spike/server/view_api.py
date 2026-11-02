"""Browser recorder API (A16): record what Spike View does into a script, list and read the scripts, replay one step by
step (the replay's questions are answered here) and stop it. Everything is for this computer's own browser only, like
the other routes that can drive the user's browser or hold what they typed: no other machine on the network, no other
web site, and no other caller (/v1, MCP, the CLI) can start, answer or read a recording or a replay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from spike.connectors.recorder import RecorderError
from spike.connectors.replay import ReplayError
from spike.connectors.scripts import ScriptError

REPLAY_CODES = {"busy": 409, "off": 409, "not_found": 404, "invalid": 400, "mode": 400}


class RecordIn(BaseModel):
    name: str = Field(default="", max_length=120)


class ReplayIn(BaseModel):
    script: str = Field(min_length=1, max_length=80)
    mode: Literal["auto", "step"] = "auto"


class AnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=40)
    decision: str = Field(min_length=1, max_length=20)
    value: str | None = Field(default=None, max_length=10_000)  # the text of a secret step: used once, never kept


def script_error(exc: ScriptError) -> HTTPException:
    return HTTPException(404 if exc.code == "not_found" else 400, str(exc))


def create_view_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter()

    def st():
        return get_state()

    def local(request: Request) -> Any:
        this_computer(request, "the browser recorder")
        return st()

    @router.get("/api/browser/recorder")
    async def recorder_status(request: Request) -> dict:
        """Whether View runs, the recording in progress, the replay, and the saved scripts: one poll for the panel."""
        state = local(request)
        return {"running": state.replayer.backend.available(), "recording": state.recorder.status(),
                "replay": state.replayer.status(), "scripts": state.scripts.list()}

    @router.post("/api/browser/recorder/start")
    async def recorder_start(body: RecordIn, request: Request) -> dict:
        state = local(request)
        if not state.replayer.backend.available():
            raise HTTPException(409, "Spike View is not running: turn it on in Settings first")
        try:
            return state.recorder.start(body.name)
        except RecorderError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/browser/recorder/stop")
    async def recorder_stop(request: Request) -> dict:
        """End the recording and keep the script (None when nothing was recorded)."""
        state = local(request)
        try:
            done = state.recorder.stop()
        except RecorderError as exc:
            raise HTTPException(409, str(exc)) from exc
        saved = {k: done[k] for k in ("id", "name", "steps", "truncated", "ignored")} if done["id"] else None
        return {"saved": saved, "recording": state.recorder.status()}

    @router.post("/api/browser/recorder/cancel")
    async def recorder_cancel(request: Request) -> dict:
        state = local(request)
        state.recorder.cancel()
        return {"recording": state.recorder.status()}

    @router.get("/api/browser/scripts/{sid}")
    async def script_get(sid: str, request: Request) -> dict:
        """The script as the JSON file kept on this computer."""
        try:
            return local(request).scripts.get(sid)
        except ScriptError as exc:
            raise script_error(exc) from exc

    @router.delete("/api/browser/scripts/{sid}")
    async def script_delete(sid: str, request: Request) -> dict:
        state = local(request)
        replay = state.replayer
        if replay.state in ("running", "waiting") and replay.sid == sid:
            raise HTTPException(409, "this script is being replayed: stop the replay first")
        if not state.scripts.delete(sid):
            raise HTTPException(404, "there is no such script")
        return {"ok": True}

    @router.post("/api/browser/scripts/{sid}/secret/{n}")
    async def script_secret(sid: str, n: int, request: Request) -> dict:
        """Make a typing step ask for its text when replayed, and drop the text kept in the file."""
        try:
            local(request).scripts.make_secret(sid, n)
        except ScriptError as exc:
            raise script_error(exc) from exc
        return {"ok": True}

    @router.post("/api/browser/replay")
    async def replay_start(body: ReplayIn, request: Request) -> dict:
        state = local(request)
        try:
            return state.replayer.start(body.script, body.mode)
        except ReplayError as exc:
            raise HTTPException(REPLAY_CODES.get(exc.code, 400), str(exc)) from exc

    @router.post("/api/browser/replay/answer")
    async def replay_answer(body: AnswerIn, request: Request) -> dict:
        if not local(request).replayer.answer(body.question, body.decision, body.value):
            raise HTTPException(409, "the replay is not waiting for that answer")
        return {"ok": True}

    @router.post("/api/browser/replay/stop")
    async def replay_stop(request: Request) -> dict:
        return {"ok": local(request).replayer.stop()}

    return router
