"""Local error log (G43): record the API's unhandled failures and let Settings read, copy and clear them.

The routes read only SPIKE_HOME/logs/errors.log and its rotated copies; the issue text is built here and copied by
the browser to the clipboard. Nothing is sent anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from spike import errorlog


class RecordFailures:
    """ASGI middleware: an exception that escapes a route (a 500) is noted with the route's template, then raised
    again so the server answers as before. HTTP errors the routes raise on purpose never get here."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            route = getattr(scope.get("route"), "path", None) or "(no route)"  # the template, never the URL
            errorlog.record("route", f"{scope.get('method', '')} {route}", exc)
            raise


def create_errors_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter(prefix="/api/errors")

    def folder():
        return get_state().home / "logs"

    @router.get("")
    def errors(request: Request, limit: int = 200) -> JSONResponse:
        this_computer(request, "the error log")
        entries = errorlog.read(folder(), min(max(limit, 1), 500))
        return JSONResponse({"entries": entries, "path": f"~/.spike/logs/{errorlog.LOG_NAME}"},
                            headers={"Cache-Control": "no-store"})

    @router.get("/report")
    def report(request: Request) -> JSONResponse:
        """The text for "copy as issue": the browser copies it; nothing leaves this computer from here."""
        this_computer(request, "the error log")
        return JSONResponse({"text": errorlog.issue_text(errorlog.read(folder(), 50))},
                            headers={"Cache-Control": "no-store"})

    @router.delete("")
    def clear(request: Request) -> dict:
        this_computer(request, "the error log")
        errorlog.clear(folder())
        return {"ok": True}

    return router


def install_error_log(app: FastAPI, get_state: Callable[[], Any], this_computer) -> None:
    """Start the log in this app's SPIKE home, record the routes' failures and add the routes."""
    errorlog.install(get_state().home / "logs")
    app.add_middleware(RecordFailures)
    app.include_router(create_errors_router(get_state, this_computer))
