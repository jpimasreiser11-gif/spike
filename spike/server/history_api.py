"""Search persisted chats locally. Queries stay in POST bodies and responses must not be cached."""

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class HistoryIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    scope: Literal['all', 'workspace', 'project'] = 'all'
    project_id: str | None = Field(default=None, max_length=128)
    match: Literal['words', 'phrase'] = 'words'
    role: Literal['all', 'user', 'assistant'] = 'all'
    after: float = Field(default=0, ge=0, allow_inf_nan=False)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=1000)


def create_history_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix='/api/history')

    @router.post('/search')
    def search(body: HistoryIn):
        store = get_state().store  # deliberately excludes the separate, in-memory temporary store
        if (body.scope == 'project') != bool(body.project_id):
            raise HTTPException(400, 'history_filter')
        if body.project_id and store.get_project(body.project_id) is None:
            raise HTTPException(404, 'project_not_found')
        try:
            result = store.search_history(**body.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    return router
