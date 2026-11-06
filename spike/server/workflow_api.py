"""Visual workflow routes (A22): the catalog of what a workflow may use, check/save/list/import/export of versioned
workflows kept in the project's folder, and runs with a live event stream, a stop button and stored records.

A run is started by one request (it returns the run's id) and followed by another (Server-Sent Events, replayed from
the first event for a reader that joins late). Permission questions are answered through the app's one endpoint,
POST /api/permissions/{id}: a run has no way to use a tool without asking the way the chat does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from spike.projects import ProjectError
from spike.runtime.paths import workspace_dir
from spike.tools.builtin import Workspace
from spike.workflows.model import (
    MAX_EDGES,
    MAX_NODES,
    Environment,
    WorkflowError,
    bind_inputs,
    clean,
    validate,
)
from spike.workflows.runner import Host, LiveRun, execute, new_record
from spike.workflows.store import WorkflowConflict, WorkflowInvalid, WorkflowNotFound, WorkflowStore

log = logging.getLogger("spike.workflows")
MAX_ACTIVE = 4  # runs going at once
KEEP_LIVE = 30  # finished runs whose event log stays in memory


class WorkflowIn(BaseModel):
    workflow: dict[str, Any]
    base_revision: int | None = Field(default=None, ge=0)


class RunIn(BaseModel):
    inputs: dict[str, Any] | None = Field(default_factory=dict)
    revision: int | None = Field(default=None, ge=1)
    provider_id: str | None = None


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_workflow_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/workflows")
    runs: dict[str, LiveRun] = {}

    # ------------------------------------------------------------------ helpers
    def usable(tool: Any) -> bool:
        """A tool a workflow may call: not the one that asks the user a question, not one that needs someone to confirm."""
        return tool.name != "ask_user" and not getattr(tool, "interactive_only", False)

    def folder_for(project_id: str | None):
        state = get_state()
        if project_id is None:
            return workspace_dir()
        if not state.store.get_project(project_id):
            raise HTTPException(404, "unknown_project")
        try:
            return state.project_files.folder(project_id)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc

    def store_for(project_id: str | None) -> WorkflowStore:
        return WorkflowStore(folder_for(project_id))

    def environment(project_id: str | None) -> Environment:
        state = get_state()
        tools = state.tools_for(project_id).all()
        return Environment(specialists=set(state.catalog.specialists),
                           tools={t.name: t.parameters for t in tools if usable(t)},
                           unavailable={t.name for t in tools if not usable(t)})

    def problems_error(exc: WorkflowError, status: int = 422) -> HTTPException:
        return HTTPException(status, {"code": "invalid_workflow", "problems": [p.to_dict() for p in exc.problems]})

    def guard(call: Callable[[], Any]) -> Any:
        """The result of a store call, with its errors as HTTP errors."""
        try:
            return call()
        except WorkflowInvalid as exc:
            raise problems_error(exc) from exc
        except WorkflowNotFound as exc:
            raise HTTPException(404, "workflow_not_found") from exc
        except WorkflowConflict as exc:
            raise HTTPException(409, "workflow_conflict") from exc
        except WorkflowError as exc:
            raise problems_error(exc, 400) from exc

    def remember(live: LiveRun) -> None:
        runs[live.record["id"]] = live
        finished = [rid for rid, r in runs.items() if r.finished]
        for rid in finished[:max(0, len(finished) - KEEP_LIVE)]:
            del runs[rid]

    def live_run(project_id: str | None, wid: str, rid: str) -> LiveRun | None:
        live = runs.get(rid)
        return live if live is not None and live.owner == (project_id, wid) else None

    def file_checker(project_id: str | None) -> Callable[[str], str | None]:
        state = get_state()

        def check(path: str) -> str | None:
            try:
                target = state.project_files.path(project_id, path) if project_id else Workspace(workspace_dir()).resolve(path)
            except (ProjectError, PermissionError) as exc:
                return str(exc)
            return None if target.is_file() else "the file does not exist"
        return check

    # ------------------------------------------------------------------ catalog and validation
    @router.get("/catalog")
    async def catalog(project_id: str | None = None) -> dict:
        """What a workflow may name, and the limits it is checked against."""
        state = get_state()
        folder_for(project_id)
        broker = state.broker
        return {"specialists": [{"id": s.id, "name": s.name} for s in state.catalog.specialists.values()],
                "tools": [{"name": t.name, "description": t.description, "risk": t.risk, "parameters": t.parameters,
                           "policy": broker.policy_for(t)} for t in state.tools_for(project_id).all() if usable(t)],
                "tools_enabled": bool(state.settings()["tools_enabled"]),
                "limits": {"nodes": MAX_NODES, "edges": MAX_EDGES}}

    @router.post("/validate")
    async def validate_workflow(body: WorkflowIn, project_id: str | None = None) -> dict:
        folder_for(project_id)
        try:
            doc = clean(body.workflow)
        except WorkflowError as exc:
            return {"ok": False, "problems": [p.to_dict() for p in exc.problems]}
        problems = validate(doc, environment(project_id))
        return {"ok": not problems, "problems": [p.to_dict() for p in problems]}

    # ------------------------------------------------------------------ saved workflows
    @router.get("")
    async def list_workflows(project_id: str | None = None) -> list[dict]:
        return guard(store_for(project_id).list)

    @router.post("")
    async def create_workflow(body: WorkflowIn, project_id: str | None = None) -> dict:
        """Save a new workflow (its first version). Nothing invalid is saved."""
        return guard(lambda: store_for(project_id).save(body.workflow, environment(project_id)))

    @router.post("/import")
    async def import_workflow(body: WorkflowIn, project_id: str | None = None) -> dict:
        """A workflow exported from here or another project, saved as a new workflow with a new id."""
        def save() -> dict:
            doc = clean(body.workflow)
            return store_for(project_id).save({k: v for k, v in doc.items() if k != "id"}, environment(project_id))
        return guard(save)

    @router.get("/{wid}")
    async def get_workflow(wid: str, project_id: str | None = None, revision: int | None = None) -> dict:
        return guard(lambda: store_for(project_id).get(wid, revision))

    @router.put("/{wid}")
    async def save_workflow(wid: str, body: WorkflowIn, project_id: str | None = None) -> dict:
        """The next version of a workflow; 409 when `base_revision` is not the newest any more."""
        store = store_for(project_id)
        guard(lambda: store.get(wid))
        return guard(lambda: store.save(body.workflow, environment(project_id), wid, body.base_revision))

    @router.delete("/{wid}")
    async def delete_workflow(wid: str, project_id: str | None = None) -> dict:
        if any(r.owner == (project_id, wid) and not r.finished for r in runs.values()):
            raise HTTPException(409, "workflow_running")
        guard(lambda: store_for(project_id).delete(wid))
        for rid in [rid for rid, r in runs.items() if r.owner == (project_id, wid)]:
            del runs[rid]
        return {"ok": True}

    @router.get("/{wid}/versions")
    async def versions(wid: str, project_id: str | None = None) -> list[dict]:
        store = store_for(project_id)
        guard(lambda: store.get(wid))
        return guard(lambda: store.versions(wid))

    @router.get("/{wid}/export")
    async def export_workflow(wid: str, project_id: str | None = None, revision: int | None = None) -> JSONResponse:
        doc = guard(lambda: store_for(project_id).get(wid, revision))
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", doc["name"]).strip("-") or "workflow"
        return JSONResponse(WorkflowStore.export(doc), headers={
            "Content-Disposition": f'attachment; filename="{slug}.spike-workflow.json"', "Cache-Control": "no-store"})

    # ------------------------------------------------------------------ runs
    @router.post("/{wid}/runs")
    async def start_run(wid: str, body: RunIn, project_id: str | None = None) -> dict:
        """Check the workflow and its inputs again, then start the run in the background; follow it with /events."""
        state = get_state()
        store = store_for(project_id)
        doc = guard(lambda: store.get(wid, body.revision))
        if problems := validate(doc, environment(project_id)):
            raise problems_error(WorkflowInvalid(problems))
        values, bad = bind_inputs(doc, body.inputs, file_checker(project_id))
        if bad:
            raise HTTPException(422, {"code": "invalid_inputs", "problems": [p.to_dict() for p in bad]})
        settings = state.settings()
        if not settings["tools_enabled"] and any(
                n["type"] == "tool" or (n["type"] == "output" and n["mode"] == "file") for n in doc["nodes"]):
            raise HTTPException(400, "tools_disabled")
        if body.provider_id and not state.provider_config(body.provider_id):
            raise HTTPException(400, f"unknown provider '{body.provider_id}'")
        if sum(1 for r in runs.values() if not r.finished) >= MAX_ACTIVE:
            raise HTTPException(429, "too_many_runs")
        await state.ensure_adapters(body.provider_id)
        await state.connectors.ensure_started()
        project = state.store.get_project(project_id) if project_id else None
        host = Host(orchestrator=state.orchestrator(body.provider_id, project_id=project_id),
                    options=lambda mode: state.options(mode, project), broker=state.broker,
                    tools_enabled=bool(settings["tools_enabled"]), parallel=bool(settings["parallel"]))
        live = LiveRun(new_record(doc, values, body.provider_id))
        live.owner = (project_id, wid)
        try:
            store.save_run(wid, live.record)
        except (OSError, WorkflowError) as exc:
            raise HTTPException(500, "run_not_stored") from exc
        remember(live)

        async def drive() -> None:
            try:
                await execute(doc, values, host, live)
            except Exception as exc:  # the record must say what happened, whatever it was
                log.warning("workflow run %s failed: %s", live.record["id"], exc.__class__.__name__)
                live.record.update(status="failed", error=exc.__class__.__name__)
                live.emit({"type": "run_end", "status": "failed"})
            finally:
                try:
                    store.save_run(wid, live.record)
                except (OSError, WorkflowError) as exc:
                    log.warning("workflow run %s was not stored: %s", live.record["id"], exc.__class__.__name__)
                live.finish()

        live.task = state.background(drive())
        return {"id": live.record["id"], "status": "running"}

    @router.get("/{wid}/runs")
    async def list_runs(wid: str, project_id: str | None = None) -> list[dict]:
        store = store_for(project_id)
        guard(lambda: store.get(wid))
        found = guard(lambda: store.list_runs(wid))
        for item in found:
            live = live_run(project_id, wid, item["id"])
            if item["status"] == "running" and (live is None or live.finished):
                item["status"] = "interrupted"  # the app stopped while it ran
        return found

    @router.get("/{wid}/runs/{rid}")
    async def get_run(wid: str, rid: str, project_id: str | None = None) -> dict:
        live = live_run(project_id, wid, rid)
        if live is not None:
            return {**live.record, "live": not live.finished}
        record = guard(lambda: store_for(project_id).get_run(wid, rid))
        return {**record, "status": "interrupted", "live": False} if record.get("status") == "running" else record

    @router.get("/{wid}/runs/{rid}/events")
    async def run_events(wid: str, rid: str, project_id: str | None = None, after: int = 0) -> StreamingResponse:
        """The run's events from `after` on, then live until it ends. Only runs of this session have events."""
        live = live_run(project_id, wid, rid)
        if live is None:
            raise HTTPException(404, "run_not_found")

        async def stream():
            async for event in live.follow(after):
                yield _sse(event)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/{wid}/runs/{rid}/stop")
    async def stop_run(wid: str, rid: str, project_id: str | None = None) -> dict:
        """Stop a run: the node that is working is cancelled (an unanswered permission question with it), the rest
        are not started, and the record is stored as `cancelled`."""
        live = live_run(project_id, wid, rid)
        if live is None or live.finished or live.task is None:
            raise HTTPException(404, "run_not_running")
        live.task.cancel()
        await asyncio.sleep(0)
        if live.task.done() and not live.finished:  # stopped before it ever started: nothing wrote its record
            live.record.update(status="cancelled", finished=round(time.time(), 3))
            live.emit({"type": "run_end", "status": "cancelled"})
            guard(lambda: store_for(project_id).save_run(wid, live.record))
            live.finish()
        try:
            await asyncio.wait_for(live.wait_finished(), timeout=10)
        except TimeoutError:
            log.warning("workflow run %s did not stop in 10 s", rid)
        return {"ok": True, "status": live.record["status"]}

    return router
