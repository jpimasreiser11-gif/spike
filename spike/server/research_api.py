"""Research: local previews, explicit one-use analysis and inert notebook downloads. Previews expire after five
minutes and bind the source bytes, project root, model and provider settings; no disk history or automatic calls.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from spike.core.context import estimate_tokens
from spike.core.types import ChatRequest, Message
from spike.providers.guard import call_cost
from spike.research import (
    MAX_OUTPUT,
    ResearchError,
    analysis_prompt,
    analysis_schema,
    load_sources,
    notebook,
    paper_blueprint,
    source_bytes,
    validate_analysis,
)


class PreviewIn(BaseModel):
    kind: Literal["paper", "contradictions"]
    paths: list[str] = Field(min_length=1, max_length=4)
    project_id: str | None = None
    provider_id: str | None = None
    language: Literal["es", "en"] = "es"


class AnalyzeIn(BaseModel):
    preview_id: str


def create_research_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/research")
    previews: dict[str, dict] = {}

    def resolve(body):
        state = get_state()
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(404, "unknown_project")
        pid, model = state.binding(state.catalog.core, body.provider_id)
        if not state.provider_config(pid):
            raise HTTPException(400, "unknown_provider")
        provider = state.provider(pid)
        root = state.prototype_root(body.project_id).resolve()
        identity = {"root": root.as_posix(), "model": model or provider.config.model,
                    "config": copy.deepcopy(state.provider_config(pid))}
        return root, provider, identity

    def blocked(provider, tokens):
        if not provider.receives_files:
            return "files_blocked"
        if provider.blocked_for(1, tokens, MAX_OUTPUT):
            return "provider_blocked"
        if provider.capabilities.max_context and tokens + MAX_OUTPUT > provider.capabilities.max_context:
            return "context_limit"
        return None

    def unchanged(root, sources):
        try:
            for source in sources:
                data = source_bytes(root, source["path"])
                if hashlib.sha256(data).hexdigest() != source["sha256"]:
                    raise ResearchError("changed_preview")
        except ResearchError as exc:
            raise HTTPException(409, "changed_preview") from exc

    @router.post("/preview")
    async def preview(body: PreviewIn) -> dict:
        if ((body.kind == "paper" and (len(body.paths) != 1 or not body.paths[0].lower().endswith(".pdf")))
                or (body.kind == "contradictions" and len(body.paths) < 2)):
            raise HTTPException(400, "invalid_sources")
        root, provider, identity = resolve(body)
        try:
            sources = await asyncio.to_thread(load_sources, root, body.paths)
        except ResearchError as exc:
            raise HTTPException(400, str(exc)) from exc
        payload = json.dumps(sources, ensure_ascii=False)
        system = analysis_prompt(body.kind, body.language)
        tokens = estimate_tokens(system) + estimate_tokens(payload)
        now = time.monotonic()
        for key in list(previews):
            if previews[key]["expires"] < now:
                del previews[key]
        if len(previews) >= 10:
            del previews[next(iter(previews))]
        qid = uuid.uuid4().hex
        previews[qid] = {"body": body, "identity": identity, "sources": sources, "payload": payload,
                         "tokens": tokens, "expires": now + 300}
        return {"id": qid, "sources": sources, "calls": 1, "provider": {"id": provider.config.id,
                "name": provider.config.name, "model": identity["model"], "local": provider.config.local},
                "blocked": blocked(provider, tokens), "estimated_cost": call_cost(provider.limits(), tokens, MAX_OUTPUT)}

    @router.post("/analyze")
    async def analyze(body: AnalyzeIn) -> dict:
        quote = previews.pop(body.preview_id, None)
        if quote is None or quote["expires"] < time.monotonic():
            raise HTTPException(409, "expired_preview")
        request = quote["body"]
        root, provider, identity = resolve(request)
        if identity != quote["identity"]:
            raise HTTPException(409, "changed_preview")
        unchanged(root, quote["sources"])
        if reason := blocked(provider, quote["tokens"]):
            raise HTTPException(403, reason)
        payload = quote["payload"]
        call = ChatRequest(messages=[Message(role="system", content=analysis_prompt(request.kind, request.language)),
                                     Message(role="user", content=payload, private=[payload])],
                           model=identity["model"], json_schema=analysis_schema(request.kind),
                           temperature=0, max_tokens=MAX_OUTPUT, reasoning=False)
        try:
            answer, _ = await asyncio.wait_for(provider.complete(call), timeout=120)
        except Exception as exc:
            raise HTTPException(502, "analysis_failed") from exc
        unchanged(root, quote["sources"])
        try:
            if len(answer) > 40_000:
                raise ResearchError("invalid_analysis")
            analysis = validate_analysis(json.loads(answer), request.kind, quote["sources"])
        except (ValueError, TypeError, RecursionError) as exc:
            raise HTTPException(422, str(exc) if isinstance(exc, ResearchError) else "invalid_analysis") from exc
        result = {"kind": request.kind, "analysis": analysis, "sources": quote["sources"]}
        if request.kind == "paper":
            result["blueprint"] = paper_blueprint(quote["sources"][0], analysis, request.language).to_dict()
        return result

    @router.get("/notebooks/{conversation_id}")
    async def export_notebook(conversation_id: str) -> JSONResponse:
        store = get_state().store_for(conversation_id)
        conv = store.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(404, "unknown_conversation")
        try:
            data = notebook(conv, store.messages(conversation_id))
        except ResearchError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="spike-research.ipynb"',
                                           "Cache-Control": "no-store"})

    return router
