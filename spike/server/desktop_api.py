"""Desktop actions API (A19): the status page for Settings, the cost estimate, a task as a Server-Sent Events stream,
the answers to its approval cards, Stop, and the screenshots the cards show. Everything that starts, answers or reads
a task is for this computer's own browser only (the same rule as real orders): a desktop task is never started, answered
or watched from another machine on the network, and no other caller (/v1, MCP, the CLI) has any way to reach it."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from spike.desktop.session import Refused
from spike.providers.guard import CURRENT_CHAT


class RunIn(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    provider_id: str | None = None
    conversation_id: str | None = None
    keep_screenshots: bool = False  # saved on this computer for the chat's proof package; never otherwise


class EstimateIn(BaseModel):
    provider_id: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=100)


class ActionIn(BaseModel):
    decision: Literal["approve", "approve_batch", "deny", "stop"]
    n: int = Field(default=1, ge=1, le=100)  # approve_batch: how many actions (the first is this one); capped at 5


def _sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


def _refuse(exc: Refused) -> HTTPException:
    return HTTPException(409 if exc.code == "busy" else 400, str(exc))


def create_desktop_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter()

    def st():
        return get_state()

    @router.get("/api/desktop")
    async def desktop_status(refresh: bool = False) -> dict:
        """The setting, what this computer can do (and what is missing), and which providers could do the actions."""
        return st().desktop.status(refresh)

    @router.post("/api/desktop/estimate")
    async def desktop_estimate(body: EstimateIn, request: Request) -> dict:
        """What a task would send and cost at most, shown before it starts."""
        this_computer(request, "desktop actions")
        try:
            return st().desktop.estimate(body.provider_id, body.max_steps)
        except Refused as exc:
            raise _refuse(exc) from exc

    @router.post("/api/desktop/run")
    async def desktop_run(body: RunIn, request: Request) -> StreamingResponse:
        this_computer(request, "desktop actions")
        state = st()
        goal = body.goal.strip()
        if not goal:
            raise HTTPException(400, "describe what the task is")
        store = state.store  # desktop tasks are never in a temporary chat: their record is for the proof package
        conv = store.get_conversation(body.conversation_id) if body.conversation_id else None
        if body.conversation_id and conv is None:
            raise HTTPException(404, "conversation not found")
        try:
            state.desktop.preflight(body.provider_id)
            if conv is None:
                title = re.sub(r"\s+", " ", goal)
                conv = store.create_conversation(title="Desktop: " + (title[:50] + "…" if len(title) > 51 else title),
                                                 mode="auto", provider_id=None, project_id=None)
            task = state.desktop.start(goal, body.provider_id, body.keep_screenshots, conv["id"])
        except Refused as exc:
            raise _refuse(exc) from exc
        user_message = store.add_message(conv["id"], "user", goal, {"desktop": True})

        async def stream() -> AsyncIterator[bytes]:
            CURRENT_CHAT.set(conv["id"])  # the call log notes which chat each model call was for
            yield _sse({"type": "desktop_conversation", "id": conv["id"], "title": conv["title"],
                        "user_message_id": user_message["id"]})
            try:
                async for ev in task.run():
                    yield _sse(ev)
            except Exception as exc:  # never leave the page waiting without a reason
                task.error, task.reason = f"{exc.__class__.__name__}: {exc}", "error"
                yield _sse({"type": "desktop_error", "message": task.error})
            finally:
                task.stop()
                record = task.record()
                if not record["reason"] or record["reason"] == "running":
                    record["reason"] = "stopped"
                # the words of the model's last answer; how the task went is the record, which the page writes in
                # the user's language
                store.add_message(conv["id"], "assistant", task.final.strip(), {"desktop": record, "error": task.error})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/api/desktop/actions/{action_id}")
    async def desktop_answer(action_id: str, body: ActionIn, request: Request) -> dict:
        """The user's answer to an approval card. Nothing runs without one."""
        this_computer(request, "desktop actions")
        desktop = st().desktop
        task = desktop.task
        if task is None or not task.running or not action_id.startswith(task.id + "_"):
            raise HTTPException(404, "no pending desktop action with this id")
        answer = desktop.broker.resolve(action_id, body.decision, body.n)
        if answer is None:
            raise HTTPException(404, "no pending desktop action with this id")
        return {"ok": True, "decision": answer.kind, "n": answer.n}

    @router.post("/api/desktop/stop")
    async def desktop_stop(request: Request) -> dict:
        """Stop the running task now (the button that is always on screen while one runs)."""
        this_computer(request, "desktop actions")
        task = st().desktop.task
        if task is None or not task.running:
            return {"ok": False}
        task.stop()
        return {"ok": True, "task": task.id}

    @router.get("/api/desktop/shots/{task_id}/{n}")
    async def desktop_shot(task_id: str, n: int, request: Request) -> Response:
        """A screenshot of the running task, for its cards. It is the user's screen: only this computer, never cached."""
        this_computer(request, "desktop screenshots")
        task = st().desktop.task
        png = task.shots.get(n) if task is not None and task.id == task_id else None
        if png is None:
            raise HTTPException(404, "screenshot not found")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    return router
