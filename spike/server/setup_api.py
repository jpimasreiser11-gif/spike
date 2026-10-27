"""Launcher-only setup endpoints. Status is local; a same-origin JSON POST authorizes transfers or quit."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from spike.launcher.setup import Setup


class DownloadIn(BaseModel):
    specialists: list[str] = Field(default_factory=list, max_length=13)


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
        if service.job["status"] == "running" or not service.resources(selected)["can_download"]:
            raise HTTPException(409, "Installation busy or insufficient resources")
        service.job.update(status="running", done=0, total=0)
        request.app.state.spike.background(service.install(selected))
        return service.job

    @router.post("/quit")
    async def quit_app(request: Request):
        setup(request, True)
        request.app.state.launcher_quit()
        return {"ok": True}

    return router
