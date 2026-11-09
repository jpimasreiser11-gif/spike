"""Launcher-only setup endpoints. Status is local; a same-origin JSON POST authorizes transfers or quit."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from spike.launcher.setup import SETUP_MESSAGES, Setup


class DownloadIn(BaseModel):
    specialists: list[str] = Field(default_factory=list, max_length=13)


class ImportIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    sha256: str | None = Field(default=None, max_length=128)


def create_setup_router() -> APIRouter:
    router = APIRouter(prefix="/api/setup")

    def setup(request: Request, mutate=False) -> Setup:
        app = request.app
        if not getattr(app.state, "launcher_enabled", False):
            raise HTTPException(404, "Launcher only")
        if mutate:
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
                    or request.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                    or (origin and (urlsplit(origin).netloc != host or urlsplit(origin).scheme != "http"))
                    or request.headers.get("sec-fetch-site") == "cross-site"):
                raise HTTPException(403, "Local same-origin JSON request required")
        if not hasattr(app.state, "model_setup"):
            app.state.model_setup = Setup(app.state.spike)
        return app.state.model_setup

    @router.get("")
    async def status(request: Request):
        if not getattr(request.app.state, "launcher_enabled", False):
            return {"enabled": False}
        return setup(request).status()

    @router.post("/download")
    async def download(request: Request, body: DownloadIn):
        service = setup(request, True)
        selected = list(dict.fromkeys(body.specialists))
        if any(s not in service.artifacts for s in selected):
            raise HTTPException(400, "Adapter unavailable")
        res = service.resources(selected)
        if service.job["status"] == "running" or not res["can_download"]:
            if not res["can_download"] and service.job["status"] != "running":
                service.job.update(
                    status="failed",
                    reason="disk",
                    resumable=False,
                    message=dict(SETUP_MESSAGES["disk"]),
                )
            raise HTTPException(409, "Installation busy or insufficient resources")
        service.job.update(
            status="running",
            done=0,
            total=0,
            reason="",
            resumable=False,
            message=dict(SETUP_MESSAGES["ready"]),
        )
        request.app.state.spike.background(service.install(selected))
        return service.job

    @router.post("/import")
    async def import_local_model(request: Request, body: ImportIn):
        service = setup(request, True)
        if service.job["status"] == "running":
            raise HTTPException(409, "Installation busy")
        try:
            dest = service.import_local(body.path, body.sha256)
        except (ValueError, OSError):
            raise HTTPException(400, detail=service.job["message"]) from None
        return {"ok": True, "model": dest.as_posix(), "job": service.job}

    @router.post("/quit")
    async def quit_app(request: Request):
        setup(request, True)
        request.app.state.launcher_quit()
        return {"ok": True}

    return router
