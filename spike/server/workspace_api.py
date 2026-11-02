"""A9 routes, separate from the app: branches, immutable artifact discussions and the heavy-job queue."""

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spike.projects import ProjectError


class ForkIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MergeIn(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    approved: Literal[True]


class VersionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)


class KnowledgeIn(BaseModel):
    specialist: str
    filename: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)


class CommentIn(BaseModel):
    line: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    parent: str | None = None


def create_workspace_router(st: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    def checked(fn, *args):
        try:
            return fn(*args)
        except (ProjectError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/projects/{pid}/fork")
    async def fork(pid: str, body: ForkIn) -> dict:
        project = checked(st().branches.fork, pid, body.name, {"auto", *st().catalog.specialists})
        for item in st().project_files.list(project["id"]):
            st().index_project_file(project["id"], item["path"])
        return project

    @router.get("/api/projects/{pid}/compare")
    async def compare(pid: str) -> dict:
        return checked(st().branches.compare, pid)

    @router.get("/api/project-branches")
    async def branches() -> list[dict]:
        return [dict(r) for r in st().store._exec("SELECT id,parent FROM project_branches")
                if st().store.get_project(r["id"]) and st().store.get_project(r["parent"])]

    @router.post("/api/projects/{pid}/merge")
    async def merge(pid: str, body: MergeIn) -> dict:
        preview = checked(st().branches.compare, pid)
        result = checked(st().branches.merge, pid, body.token)
        for item in preview["files"]:
            if item["deleted"]:
                st().memory.store.delete_source(f"project:{preview['parent']}", f"file:{item['path']}")
            else:
                st().index_project_file(preview["parent"], item["path"])
        return result

    @router.post("/api/artifact-versions")
    async def version(body: VersionIn) -> dict:
        return st().discussions.version(body.title, body.content)

    @router.get("/api/artifact-versions/{aid}/comments")
    async def comments(aid: str) -> list[dict]:
        return st().discussions.comments(aid)

    @router.post("/api/artifact-versions/{aid}/comments")
    async def comment(aid: str, body: CommentIn) -> dict:
        return checked(st().discussions.add, aid, body.line, body.text, body.parent)

    @router.post("/api/specialist-documents")
    async def document(body: KnowledgeIn) -> dict:
        if body.specialist not in st().catalog.specialists:
            raise HTTPException(400, "unknown specialist")
        return checked(st().memory.store.replace_source, f"specialist:{body.specialist}",
                       f"file:{body.filename}", body.text, "document").public()

    @router.get("/api/jobs")
    async def jobs() -> dict:
        queue = st().jobs
        return {"limit": queue.limit, "ram_floor": queue.ram_floor, "jobs": queue.list()}

    @router.post("/api/jobs/{jid}/cancel")
    async def cancel(jid: str) -> dict:
        if not st().jobs.cancel(jid):
            raise HTTPException(404, "job not found")
        return {"ok": True}

    return router
