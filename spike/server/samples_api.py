"""Sample projects (G39): list the bundled samples and import one with a single request. The import goes through the
same `import_project` as an uploaded archive, then indexes the files for search like `/api/projects/import` does."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from spike.projects import ProjectError, import_project
from spike.samples import build_archive, list_samples


def create_samples_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/samples")

    @router.get("")
    async def samples(lang: str = "en") -> list[dict]:
        return list_samples(lang)

    @router.post("/{sample_id}/import")
    async def import_sample(sample_id: str, lang: str = "en") -> dict:
        try:
            blob = build_archive(sample_id, lang)
        except KeyError as exc:
            raise HTTPException(404, "unknown_sample") from exc
        state = get_state()
        try:
            project = import_project(state.store, state.project_files, blob, {"auto", *state.catalog.specialists},
                                     state.memory.store)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        for f in state.project_files.list(project["id"]):
            state.index_project_file(project["id"], f["path"])
        return project

    return router
