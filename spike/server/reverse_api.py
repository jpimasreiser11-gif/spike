"""Reverse Studio routes (A20): a reference the user owns becomes one editable HTML/CSS file.

Two steps, like Research: `preview` checks the request, records the user's confirmation that they own the reference or
may use it (a request without it is refused with 400), and returns what would leave this computer and why it might be
blocked; `generate` runs once from that preview. An image is only sent to a provider that supports vision, may bill
(`allow_paid`), may receive files (`share_files`) and is inside its monthly limits: the checks `GuardedProvider` already
makes for every file. A page on this computer is read in a headless browser and only its layout and styles, with
placeholder text, reach the model. The result is saved in the project (or the workspace) under `reverse/`, with a JSON
record that carries the confirmation, and shown in the artifacts panel."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from spike.core.context import estimate_tokens
from spike.core.types import ChatRequest, Message, ProviderError
from spike.design import reverse, reverse_browser
from spike.design.reverse import ReverseError
from spike.media import MediaError, validate_images
from spike.projects import ProjectError
from spike.providers.guard import call_cost
from spike.runtime.paths import workspace_dir
from spike.tools.builtin import Workspace

MAX_OUTPUT = 6000
DEFAULT_CONTEXT = 8192  # when the provider does not declare one: what a small local model usually runs with
QUOTE_SECONDS = 300
FILE_PATH = re.compile(r"reverse/[a-z0-9-]{1,60}\.html")


class ReverseIn(BaseModel):
    authorized: Any = False  # "I own this or have permission to use it": anything but true is refused with 400
    source: Literal["image", "url", "file"]
    image: str | None = Field(default=None, max_length=3_000_000)  # a data URL, as in the chat
    url: str | None = Field(default=None, max_length=2000)
    path: str | None = Field(default=None, max_length=500)  # a page in the project (or workspace)
    project_id: str | None = Field(default=None, max_length=128)
    provider_id: str | None = Field(default=None, max_length=128)
    width: int | None = Field(default=None, ge=240, le=2560)  # the viewport of a page; an image has its own size
    height: int | None = Field(default=None, ge=200, le=4096)
    own_text: str = Field(default="", max_length=4000)
    avoid: list[str] = Field(default_factory=list, max_length=20)


class GenerateIn(BaseModel):
    preview_id: str


class FileIn(BaseModel):
    project_id: str | None = Field(default=None, max_length=128)
    path: str = Field(max_length=200)
    html: str = Field(min_length=1, max_length=reverse.MAX_HTML)


def create_reverse_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter(prefix="/api/reverse")
    quotes: dict[str, dict] = {}
    busy = asyncio.Lock()  # one browser job at a time

    def resolve(body: ReverseIn):
        state = get_state()
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(404, "reverse_unknown_project")
        pid, model = state.binding(state.catalog.core, body.provider_id)
        if not state.provider_config(pid):
            raise HTTPException(400, "reverse_unknown_provider")
        provider = state.provider(pid)
        return provider, {"model": model or provider.config.model, "project": body.project_id,
                          "config": copy.deepcopy(state.provider_config(pid))}

    def folder_of(body: ReverseIn):
        state = get_state()
        return state.project_files.folder(body.project_id) if body.project_id else workspace_dir()

    def check_source(body: ReverseIn) -> tuple[int, int]:
        """The size of the reference, after checking that it is what it says it is."""
        if body.source == "image":
            validate_images([body.image or ""])
            raw = base64.b64decode((body.image or "").partition(",")[2])
            return reverse.image_size(raw)
        if body.source == "url":
            reverse.check_url(body.url or "")
        else:
            path = reverse.check_page_path(body.path or "")
            state = get_state()
            try:
                target = (state.project_files.path(body.project_id, path) if body.project_id
                          else Workspace(workspace_dir()).resolve(path))
            except (ProjectError, PermissionError) as exc:
                raise ReverseError("reverse_path") from exc
            if not target.is_file():
                raise ReverseError("reverse_path")
        return body.width or 1280, body.height or 800

    def budget(provider, system: str) -> tuple[int, int, int]:
        """(context, output tokens, tokens left for the description of a page)."""
        context = provider.capabilities.max_context or DEFAULT_CONTEXT
        out = min(MAX_OUTPUT, context // 2)
        return context, out, context - out - estimate_tokens(system) - 400

    def blocked(provider, kind: str, tokens: int, context: int, out: int) -> str | None:
        if not provider.receives_files:
            return "images_private" if kind == "image" else "reverse_files_blocked"
        if provider.blocked_for(1, tokens, out):
            return "reverse_provider_blocked"
        if tokens + out > context:
            return "reverse_context"
        return None

    def reason_of(exc: Exception) -> tuple[int, str]:
        code = str(exc)
        if code == "reverse_browser_missing":
            return 503, code
        if code in ("reverse_capture_failed", "reverse_failed"):
            return 502, code
        return 400, code

    @router.get("")
    async def status(request: Request) -> dict:
        this_computer(request, "Reverse Studio")
        state = get_state()
        rows = []
        for cfg in state.provider_configs():
            try:
                provider = state.provider(cfg["id"])
                rows.append({"id": cfg["id"], "name": cfg["name"], "local": bool(cfg.get("local")),
                             "paid": bool(cfg.get("paid")), "allow_paid": bool(cfg.get("allow_paid")),
                             "vision": bool(provider.capabilities.vision), "receives_files": provider.receives_files})
            except Exception:  # noqa: BLE001 - a provider that cannot be built is simply not offered
                continue
        return {"browser": reverse_browser.available(), "providers": rows, "statement": reverse.STATEMENT,
                "default_provider": state.binding(state.catalog.core, None)[0]}

    @router.post("/preview")
    async def preview(body: ReverseIn, request: Request) -> dict:
        this_computer(request, "Reverse Studio")
        if body.authorized is not True:
            raise HTTPException(400, "reverse_authorization")
        provider, identity = resolve(body)  # an unknown project or provider first: nothing is created for it
        try:
            size = check_source(body)
        except (ReverseError, MediaError) as exc:
            raise HTTPException(400, str(exc)) from exc
        kind = "image" if body.source == "image" else "structure"
        if kind == "image" and not provider.capabilities.vision:
            raise HTTPException(400, "reverse_vision_required")
        system = reverse.system_prompt()
        context, out, room = budget(provider, system)
        if room < 500:
            raise HTTPException(403, "reverse_context")
        tokens = estimate_tokens(system) + (estimate_tokens(reverse.image_prompt(*size, body.own_text, body.avoid))
                                            if kind == "image" else room)
        now = time.monotonic()
        for key in [k for k, v in quotes.items() if v["expires"] < now]:
            del quotes[key]
        if len(quotes) >= 20:
            del quotes[next(iter(quotes))]
        reference = body.image if body.source == "image" else body.url if body.source == "url" else body.path
        record = reverse.authorization(
            body.source, reverse.sha256_image(reference or "") if kind == "image" else reference or "",
            kind="image" if kind == "image" else body.source)
        qid = uuid.uuid4().hex
        quotes[qid] = {"body": body, "identity": identity, "expires": now + QUOTE_SECONDS, "size": size,
                       "authorization": record, "room": room, "out": out, "tokens": tokens}
        return {"id": qid, "source": body.source, "size": {"width": size[0], "height": size[1]},
                "provider": {"id": provider.config.id, "name": provider.config.name, "model": identity["model"],
                             "local": provider.config.local},
                "sends": kind, "egress": not provider.config.local,
                "blocked": blocked(provider, kind, tokens, context, out),
                "estimated_cost": call_cost(provider.limits(), tokens, out), "authorization": record}

    def save(body: ReverseIn, name: str, doc: str, record: dict[str, Any]) -> str:
        state = get_state()
        relative = f"reverse/{name}.html"
        side = json.dumps(record, ensure_ascii=False, indent=1).encode("utf-8")
        try:
            if body.project_id:
                state.project_files.write(body.project_id, relative, doc.encode("utf-8"))
                state.project_files.write(body.project_id, f"reverse/{name}.json", side)
            else:
                root = Workspace(workspace_dir())
                for suffix, data in ((".html", doc.encode("utf-8")), (".json", side)):
                    target = root.resolve(f"reverse/{name}{suffix}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        except (ProjectError, PermissionError, OSError) as exc:
            raise HTTPException(400, "reverse_path") from exc
        return relative

    @router.post("/generate")
    async def generate(body: GenerateIn, request: Request) -> dict:
        this_computer(request, "Reverse Studio")
        if busy.locked():
            raise HTTPException(409, "reverse_busy")
        quote = quotes.pop(body.preview_id, None)
        if quote is None or quote["expires"] < time.monotonic():
            raise HTTPException(409, "reverse_expired")
        req: ReverseIn = quote["body"]
        provider, identity = resolve(req)
        if identity != quote["identity"]:
            raise HTTPException(409, "reverse_changed")
        width, height = quote["size"]
        kind = "image" if req.source == "image" else "structure"
        system = reverse.system_prompt()
        avoid = [a.strip()[:80] for a in req.avoid if a.strip()]
        context = provider.capabilities.max_context or DEFAULT_CONTEXT
        if reason := blocked(provider, kind, quote["tokens"], context, quote["out"]):  # before any work is done
            raise HTTPException(403, reason)
        async with busy:
            capture: dict[str, Any] = {}
            if kind == "image":
                reference = req.image or ""
                user = Message(role="user", content=reverse.image_prompt(width, height, req.own_text, avoid),
                               images=[reference])
                tokens = estimate_tokens(system) + estimate_tokens(user.content)
            else:
                try:
                    capture = await reverse_browser.capture_page(
                        url=req.url, folder=folder_of(req) if req.source == "file" else None, path=req.path,
                        width=width, height=height)
                except ReverseError as exc:
                    raise HTTPException(*reason_of(exc)) from exc
                reference = "data:image/png;base64," + base64.b64encode(capture.pop("png")).decode("ascii")
                text = reverse.structure_prompt(reverse.describe(capture, req.own_text, quote["room"]),
                                                req.own_text, avoid)
                user = Message(role="user", content=text, private=[text])  # a page of the user's: file content
                tokens = estimate_tokens(system) + estimate_tokens(text)
            if reason := blocked(provider, kind, tokens, context, quote["out"]):  # again, with the real size
                raise HTTPException(403, reason)
            call = ChatRequest(messages=[Message(role="system", content=system), user], model=identity["model"],
                               temperature=0.2, max_tokens=quote["out"], reasoning=False)
            try:
                answer, _ = await asyncio.wait_for(provider.complete(call), timeout=600)
            except ProviderError as exc:
                known = {"vision_required": (400, "reverse_vision_required"), "images_private": (403, "images_private")}
                raise HTTPException(*known.get(str(exc), (502, "reverse_failed"))) from exc
            except TimeoutError as exc:
                raise HTTPException(502, "reverse_failed") from exc
            names = reverse.brand_names(capture.get("names", []), req.own_text, avoid)
            try:
                doc, removed = reverse.clean_document(answer, names)
            except ReverseError as exc:
                raise HTTPException(422, str(exc)) from exc
            try:  # the score is a measurement of this render; without a browser there is none
                fidelity = {"measured": True, **await reverse_browser.measure(doc, reference, width, height),
                            "against": "image" if kind == "image" else "page"}
            except ReverseError as exc:
                fidelity = {"measured": False, "reason": str(exc)}
        name = f"reverse-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        sent = {"what": kind, "to": provider.config.name, "remote": not provider.config.local}
        record = {"authorization": quote["authorization"], "source": req.source, "size": {"width": width, "height": height},
                  "provider": {"id": provider.config.id, "name": provider.config.name, "model": identity["model"]},
                  "sent": sent, "fidelity": fidelity, "removed": removed, "names_removed": names,
                  "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        path = save(req, name, doc, record)
        title = re.search(r"<title>(.*?)</title>", doc, re.DOTALL)
        return {**record, "html": doc, "title": title.group(1).strip() if title else "Reverse Studio",
                "filename": f"{name}.html", "path": path, "project_id": req.project_id}

    @router.put("/file")
    async def save_file(body: FileIn, request: Request) -> dict:
        """The user's edits to a file Reverse Studio made: only `reverse/*.html` that exists, in the project or the
        workspace."""
        this_computer(request, "Reverse Studio")
        if not FILE_PATH.fullmatch(body.path):
            raise HTTPException(400, "reverse_path")
        state = get_state()
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(404, "reverse_unknown_project")
        try:
            target = (state.project_files.path(body.project_id, body.path) if body.project_id
                      else Workspace(workspace_dir()).resolve(body.path))
        except (ProjectError, PermissionError) as exc:
            raise HTTPException(400, "reverse_path") from exc
        if not target.is_file():
            raise HTTPException(404, "reverse_file_missing")
        data = body.html.encode("utf-8")
        target.write_bytes(data)
        return {"path": body.path, "size": len(data)}

    return router
