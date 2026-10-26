"""Neural Memory extensions over HTTP: indexed folders, glossaries, tutor progress and the knowledge graph.

Kept apart from `app.py` like the `/v1` router: `create_memory_router` gets the app's state and its two request
checks (a valid memory scope, and "this request comes from the computer SPIKE runs on")."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from spike.memory.folders import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    FolderError,
)
from spike.memory.glossary import GlossaryError
from spike.memory.graph import GraphError
from spike.memory.graph_svg import render_svg
from spike.memory.tutor import TutorError

MAX_CSV_BYTES = 5 * 1024**2


class FolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    scope: str = "global"
    include: list[str] | None = Field(default=None, max_length=100)
    exclude: list[str] | None = Field(default=None, max_length=100)
    max_file_bytes: int | None = None
    max_files: int | None = None


class FolderPatch(BaseModel):
    include: list[str] | None = Field(default=None, max_length=100)
    exclude: list[str] | None = Field(default=None, max_length=100)
    max_file_bytes: int | None = None
    max_files: int | None = None


class ReindexIn(BaseModel):
    force: bool = False  # read every file again, not only the ones whose time or size changed


class GlossaryIn(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=1000)
    lang: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=500)
    scope: str = "global"


class GlossaryPatch(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=200)
    translation: str | None = Field(default=None, min_length=1, max_length=1000)
    lang: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope: str = "global"
    notes: str = Field(default="", max_length=1000)
    mastery: int = 0  # how well the learner already knows it, 0 to 5


class TopicPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class ReviewIn(BaseModel):
    grade: int = Field(ge=0, le=5)  # 0 blank ... 5 perfect; below 3 counts as forgotten


class RelationIn(BaseModel):
    scope: str = "global"
    source: str = Field(min_length=1, max_length=300)  # an entity id ("e:12") or its name
    label: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=300)


class RelationPatch(BaseModel):
    status: Literal["proposed", "confirmed", "rejected"]


class ProposeIn(BaseModel):
    memory_id: str = Field(min_length=1, max_length=64)
    provider_id: str | None = None


async def read_body(request: Request, limit: int) -> bytes:
    if int(request.headers.get("content-length") or 0) > limit:
        raise HTTPException(413, f"the upload is limited to {limit // 1024**2} MB")
    data = await request.body()
    if len(data) > limit:
        raise HTTPException(413, f"the upload is limited to {limit // 1024**2} MB")
    return data


def create_memory_router(get_state: Callable[[], Any], check_scope: Callable[[str], str],
                         this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter()

    def st():
        return get_state()

    # ---------------------------------------------------------------- indexed folders
    def folder_or_404(folder_id: str):
        folder = st().memory.folders.get(folder_id)
        if folder is None:
            raise HTTPException(404, "folder not found")
        return folder

    @router.get("/api/memory-folders")
    async def list_folders() -> dict:
        index = st().memory.folders
        return {"folders": [index.public(f) for f in index.list()],
                "defaults": {"include": list(DEFAULT_INCLUDE), "exclude": list(DEFAULT_EXCLUDE),
                             "max_file_bytes": DEFAULT_MAX_FILE_BYTES, "max_files": DEFAULT_MAX_FILES}}

    @router.post("/api/memory-folders")
    async def add_folder(body: FolderIn, request: Request) -> dict:
        this_computer(request, "choosing folders to index")  # a path on this disk, chosen from this computer
        index = st().memory.folders
        try:
            folder = index.add(body.path, check_scope(body.scope), body.include, body.exclude, body.max_file_bytes,
                               body.max_files)
        except FolderError as exc:
            raise HTTPException(400, str(exc)) from exc
        index.start(folder.id, spawn=st().background)
        return index.public(folder)

    @router.get("/api/memory-folders/{folder_id}")
    async def get_folder(folder_id: str) -> dict:
        return st().memory.folders.public(folder_or_404(folder_id))

    @router.get("/api/memory-folders/{folder_id}/files")
    async def folder_files(folder_id: str, limit: int = 500) -> list[dict]:
        folder_or_404(folder_id)
        return st().memory.folders.files(folder_id, min(max(limit, 1), 5000))

    @router.patch("/api/memory-folders/{folder_id}")
    async def patch_folder(folder_id: str, body: FolderPatch, request: Request) -> dict:
        this_computer(request, "changing the rules of an indexed folder")
        index = st().memory.folders
        try:
            folder = index.update(folder_id, body.include, body.exclude, body.max_file_bytes, body.max_files)
        except FolderError as exc:
            raise HTTPException(400, str(exc)) from exc
        if folder is None:
            raise HTTPException(404, "folder not found")
        index.start(folder_id, spawn=st().background)
        return index.public(folder)

    @router.post("/api/memory-folders/{folder_id}/reindex")
    async def reindex_folder(folder_id: str, body: ReindexIn | None = None) -> dict:
        folder = folder_or_404(folder_id)
        index = st().memory.folders
        index.start(folder_id, bool(body and body.force), spawn=st().background)
        return index.public(folder)

    @router.delete("/api/memory-folders/{folder_id}")
    async def forget_folder(folder_id: str) -> dict:
        gone = st().memory.folders.forget(folder_id)
        if gone is None:
            raise HTTPException(404, "folder not found")
        return {"ok": True, **gone}

    # ---------------------------------------------------------------- glossaries
    def glossary_or_400(fn, *args):
        try:
            return fn(*args)
        except GlossaryError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/glossary")
    async def list_glossary(scope: str | None = None, q: str | None = None, limit: int = 1000) -> list[dict]:
        entries = st().memory.glossary.list(check_scope(scope) if scope else None, q, min(max(limit, 1), 5000))
        return [e.public() for e in entries]

    @router.post("/api/glossary")
    async def add_glossary(body: GlossaryIn) -> dict:
        return glossary_or_400(st().memory.glossary.add, body.term, body.translation, body.lang, body.note,
                               check_scope(body.scope)).public()

    @router.get("/api/glossary-export")
    async def export_glossary(scope: str = "global") -> Response:
        csv_text = st().memory.glossary.export_csv(check_scope(scope))
        return Response("﻿" + csv_text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="spike-glossary.csv"'})

    @router.post("/api/glossary-import")
    async def import_glossary(request: Request, scope: str = "global") -> dict:
        data = await read_body(request, MAX_CSV_BYTES)
        return glossary_or_400(st().memory.glossary.import_csv, data, check_scope(scope))

    @router.put("/api/glossary/{entry_id}")
    async def update_glossary(entry_id: str, body: GlossaryPatch) -> dict:
        entry = glossary_or_400(st().memory.glossary.update, entry_id, body.term, body.translation, body.lang,
                                body.note)
        if entry is None:
            raise HTTPException(404, "entry not found")
        return entry.public()

    @router.delete("/api/glossary/{entry_id}")
    async def delete_glossary(entry_id: str) -> dict:
        if not st().memory.glossary.delete(entry_id):
            raise HTTPException(404, "entry not found")
        return {"ok": True}

    # ---------------------------------------------------------------- tutor progress
    def tutor_or_400(fn, *args):
        try:
            return fn(*args)
        except TutorError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/tutor")
    async def list_topics(scope: str | None = None, due: bool = False) -> dict:
        tutor = st().memory.tutor
        now = tutor.clock()
        topics = tutor.list([check_scope(scope)] if scope else None, due_only=due, limit=5000)
        return {"now": now, "due": sum(t.due(now) for t in topics), "topics": [t.public(now) for t in topics]}

    @router.post("/api/tutor")
    async def add_topic(body: TopicIn) -> dict:
        tutor = st().memory.tutor
        topic = tutor_or_400(tutor.add, body.name, check_scope(body.scope), body.notes, body.mastery)
        return topic.public(tutor.clock())

    @router.patch("/api/tutor/{topic_id}")
    async def patch_topic(topic_id: str, body: TopicPatch) -> dict:
        tutor = st().memory.tutor
        topic = tutor_or_400(tutor.rename, topic_id, body.name, body.notes)
        if topic is None:
            raise HTTPException(404, "topic not found")
        return topic.public(tutor.clock())

    @router.post("/api/tutor/{topic_id}/review")
    async def review_topic(topic_id: str, body: ReviewIn) -> dict:
        tutor = st().memory.tutor
        topic = tutor_or_400(tutor.review, topic_id, body.grade)
        if topic is None:
            raise HTTPException(404, "topic not found")
        return topic.public(tutor.clock())

    @router.delete("/api/tutor/{topic_id}")
    async def delete_topic(topic_id: str) -> dict:
        if not st().memory.tutor.delete(topic_id):
            raise HTTPException(404, "topic not found")
        return {"ok": True}

    # ---------------------------------------------------------------- knowledge graph
    def graph_scopes(scope: str | None) -> list[str]:
        if scope:
            return [check_scope(scope)]
        return ["global", *(f"project:{p['id']}" for p in st().store.list_projects())]

    def graph_or_400(fn, *args):
        try:
            return fn(*args)
        except GraphError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def synced():
        await asyncio.to_thread(st().memory.graph.sync)  # reads only the notes added or changed since last time
        return st().memory.graph

    @router.get("/api/memory-graph")
    async def memory_graph(scope: str | None = None, node: str | None = None, depth: int = 1, limit: int = 30,
                           notes: bool = True, proposed: bool = False) -> dict:
        graph = await synced()
        scopes = graph_scopes(scope)
        data = graph_or_400(graph.graph, scopes, node, depth, limit, notes, proposed)
        return {**data, "stats": graph.stats(scopes)}

    @router.get("/api/memory-graph/svg")
    async def memory_graph_svg(scope: str | None = None, node: str | None = None, depth: int = 1, limit: int = 30,
                               notes: bool = True, proposed: bool = False, lang: str = "en") -> Response:
        graph = await synced()
        data = graph_or_400(graph.graph, graph_scopes(scope), node, depth, limit, notes, proposed)
        focus = next((n["label"] for n in data["nodes"] if n["id"] == node), None)
        return Response(render_svg(data, lang, focus), media_type="image/svg+xml", headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff"})

    @router.get("/api/memory-graph/entities")
    async def graph_entities(scope: str | None = None, q: str | None = None, kind: str | None = None,
                             limit: int = 50) -> list[dict]:
        graph = await synced()
        return graph.entities(graph_scopes(scope), q, kind, min(max(limit, 1), 200))

    @router.get("/api/memory-graph/relations")
    async def graph_relations(scope: str | None = None, status: str | None = None) -> list[dict]:
        return graph_or_400(lambda: st().memory.graph.relations(graph_scopes(scope), status))

    @router.post("/api/memory-graph/relations")
    async def add_relation(body: RelationIn) -> dict:
        await synced()
        return graph_or_400(lambda: st().memory.graph.add_relation(check_scope(body.scope), body.source, body.label,
                                                                    body.target))

    @router.patch("/api/memory-graph/relations/{relation_id}")
    async def patch_relation(relation_id: str, body: RelationPatch) -> dict:
        relation = graph_or_400(lambda: st().memory.graph.set_status(relation_id, body.status))
        if relation is None:
            raise HTTPException(404, "relation not found")
        return relation

    @router.delete("/api/memory-graph/relations/{relation_id}")
    async def delete_relation(relation_id: str) -> dict:
        if not st().memory.graph.delete_relation(relation_id):
            raise HTTPException(404, "relation not found")
        return {"ok": True}

    @router.post("/api/memory-graph/propose")
    async def propose_relations(body: ProposeIn) -> dict:
        """Ask the local model for relations between the entities of one note; the answers are proposals."""
        try:
            return {"proposed": await st().propose_relations(body.memory_id, body.provider_id)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except GraphError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    return router
