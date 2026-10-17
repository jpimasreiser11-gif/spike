"""SPIKE HTTP API (FastAPI) and static web app."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spike import __version__
from spike.core.types import Message
from spike.packs import MAX_BYTES as MAX_PACK_BYTES
from spike.packs import export_pack, install_skills_zip, read_pack
from spike.projects import MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, ProjectError, export_project, import_project
from spike.providers.registry import KINDS, PRESETS, PRESETS_BY_ID
from spike.runtime.hardware import detect, recommend
from spike.runtime.paths import workspace_dir
from spike.server.openai_api import create_router
from spike.server.state import AppState
from spike.tools.builtin import Workspace


class Limits(BaseModel):
    """Monthly limits for one provider; prices are what the user pays per million tokens, in their own currency."""

    monthly_tokens: int | None = Field(default=None, ge=1)
    monthly_cost: float | None = Field(default=None, ge=0)
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)


class ProviderIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    preset: str | None = None
    kind: str | None = None
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    paid: bool | None = None
    allow_paid: bool | None = None
    share_files: bool | None = None
    limits: Limits | None = None
    capabilities: dict[str, Any] | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=200_000)
    conversation_id: str | None = None
    mode: str = "auto"
    provider_id: str | None = None
    project_id: str | None = None  # for a new chat; an existing chat keeps its own project
    replace_from: str | None = None  # a user message of this chat: it and everything after it are replaced (edit, retry)


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    kind: str = "fact"
    scope: str = "global"


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=20_000)
    kind: str | None = None


class NewConversation(BaseModel):
    project_id: str | None = None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=100_000)
    mode: str = "auto"


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=100_000)
    mode: str | None = None


class ConnectorPatch(BaseModel):
    enabled: bool | None = None
    policy: str | None = None
    secrets: dict[str, str] | None = None


class CustomConnectorIn(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    description: str = ""


class SkillPatch(BaseModel):
    enabled: bool


class DecisionIn(BaseModel):
    decision: str


class ConversationPatch(BaseModel):
    title: str | None = None
    mode: str | None = None
    provider_id: str | None = None


def _sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


def _title_from(text: str) -> str:
    line = re.sub(r"\s+", " ", text).strip()
    return (line[:57] + "…") if len(line) > 58 else line or "New chat"


def static_dir() -> Path | None:
    for candidate in (Path(__file__).with_name("static"), Path(__file__).resolve().parents[2] / "web" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _hostname(value: str, url: bool) -> str | None:
    try:
        return urlsplit(value if url else f"//{value}").hostname
    except ValueError:
        return None


def create_app(state: AppState | None = None, allowed_hosts: set[str] | None = None) -> FastAPI:
    """`allowed_hosts`: the names the server may be reached by. Any other Host or Origin header is refused, so a web
    page that points its own domain at 127.0.0.1 (DNS rebinding) or calls from another site cannot use SPIKE."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.spike.close()  # MCP servers, the embedding server and background tasks end with SPIKE

    app = FastAPI(title="SPIKE", version=__version__, lifespan=lifespan)
    app.state.spike = state or AppState()

    def st() -> AppState:
        return app.state.spike

    if allowed_hosts is not None:
        allowed = {h.lower().strip("[]") for h in allowed_hosts}

        @app.middleware("http")
        async def check_host(request: Request, call_next):
            origin = request.headers.get("origin")
            for value, url in ((request.headers.get("host", ""), False), (origin, True)):
                if (value is not None or not url) and _hostname(value or "", url) not in allowed:
                    return JSONResponse({"error": {"message": "request refused: unknown Host or Origin",
                                                   "type": "permission_error"}}, status_code=403)
            return await call_next(request)

    app.include_router(create_router(st))

    # ---------------------------------------------------------------- system
    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/system")
    async def system() -> dict:
        hw = detect()
        rt = st().runtime
        return {
            "version": __version__,
            "hardware": hw.to_dict(),
            "recommendation": asdict(recommend(hw)),
            "runtime": rt.status() if rt else {"running": False},
            "secrets_backend": st().secrets.backend,
            "home": str(st().home),
        }

    # ---------------------------------------------------------------- specialists & tools
    @app.get("/api/specialists")
    async def specialists() -> list[dict]:
        return [s.public() for s in st().catalog.specialists.values()]

    @app.get("/api/tools")
    async def tools() -> list[dict]:
        broker = st().broker
        return [{"name": t.name, "description": t.description, "risk": t.risk, "default_policy": t.default_policy,
                 "policy": broker.policy_for(t)} for t in st().tools.all()]

    # ---------------------------------------------------------------- skills and packs
    def skill_or_404(name: str):
        skill = st().skills.get(name)
        if skill is None:
            raise HTTPException(404, "skill not found")
        return skill

    @app.get("/api/skills")
    async def skills() -> list[dict]:
        disabled = set(st().settings()["disabled_skills"])
        return [s.public(s.name not in disabled) for s in st().skills.all()]

    @app.get("/api/skills/{name}")
    async def get_skill(name: str) -> dict:
        skill = skill_or_404(name)
        return skill.public(name not in st().settings()["disabled_skills"]) | {"body": skill.body()}

    @app.put("/api/skills/{name}")
    async def toggle_skill(name: str, body: SkillPatch) -> dict:
        skill = skill_or_404(name)
        disabled = [n for n in st().settings()["disabled_skills"] if n != name] + ([] if body.enabled else [name])
        st().update_settings({"disabled_skills": disabled})
        return skill.public(body.enabled)

    @app.post("/api/skills/import")
    async def import_skills(request: Request) -> dict:
        blob = await read_body(request, MAX_PACK_BYTES)
        try:
            names = install_skills_zip(blob, st().home / "skills")
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        st().skills.reload()
        return {"names": names}

    @app.delete("/api/skills/{name}")
    async def delete_skill(name: str) -> dict:
        skill = skill_or_404(name)
        if skill.source != "user":
            raise HTTPException(400, "built-in skills can be disabled, not deleted")
        shutil.rmtree(skill.path)
        st().skills.reload()
        return {"ok": True}

    @app.get("/api/pack/export")
    async def pack_export() -> Response:
        state = st()
        user_skills = [s.path for s in state.skills.all() if s.source == "user"]
        blob = export_pack(state.settings()["custom_specialists"], state.store.get_setting("custom_connectors", []),
                           user_skills)
        return Response(blob, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="spike-pack.zip"'})

    @app.post("/api/pack/import")
    async def pack_import(request: Request) -> dict:
        state = st()
        blob = await read_body(request, MAX_PACK_BYTES)
        try:
            manifest, skill_names = read_pack(blob, state.home / "skills")
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        state.skills.reload()
        current = state.settings()["custom_specialists"]
        new_specs = [s for s in manifest.get("specialists") or []
                     if isinstance(s, dict) and s.get("id") and s["id"] not in state.catalog.specialists]
        if new_specs:
            try:
                state.update_settings({"custom_specialists": current + new_specs})
            except (ValueError, KeyError) as exc:
                state.update_settings({"custom_specialists": current})
                raise HTTPException(400, f"invalid specialist in pack: {exc}") from exc
        added_connectors = []
        for raw in manifest.get("connectors") or []:
            try:
                state.connectors.add_custom({k: v for k, v in raw.items() if k != "headers"})
                added_connectors.append(raw["id"])
            except (ValueError, KeyError, TypeError):
                continue  # already present or invalid: skipped, never overwritten
        return {"specialists": [s["id"] for s in new_specs], "skills": skill_names, "connectors": added_connectors}

    # ---------------------------------------------------------------- connectors (MCP)
    def connector_view(cid: str) -> dict:
        definition = st().connectors.get(cid)
        if definition is None:
            raise HTTPException(404, "connector not found")
        return st().connectors.public(definition, st().broker.policy_for)

    @app.get("/api/connectors")
    async def connectors() -> list[dict]:
        return [st().connectors.public(d, st().broker.policy_for) for d in st().connectors.definitions()]

    @app.post("/api/connectors")
    async def add_connector(body: CustomConnectorIn) -> dict:
        try:
            definition = st().connectors.add_custom(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return connector_view(definition.id)

    @app.put("/api/connectors/{cid}")
    async def update_connector(cid: str, body: ConnectorPatch) -> dict:
        connector_view(cid)
        try:
            await st().connectors.update(cid, enabled=body.enabled, policy=body.policy, secrets=body.secrets)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return connector_view(cid)

    @app.delete("/api/connectors/{cid}")
    async def delete_connector(cid: str) -> dict:
        connector_view(cid)
        try:
            await st().connectors.remove_custom(cid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    # ---------------------------------------------------------------- providers
    @app.get("/api/presets")
    async def presets() -> list[dict]:
        return [asdict(p) for p in PRESETS]

    @app.get("/api/providers")
    async def providers() -> list[dict]:
        return [st().public_provider(p) for p in st().provider_configs()]

    @app.post("/api/providers")
    async def add_provider(body: ProviderIn) -> dict:
        preset = PRESETS_BY_ID.get(body.preset or "")
        pid = body.id or (preset.id if preset else None)
        if not pid:
            raise HTTPException(400, "id or preset is required")
        if st().provider_config(pid):
            raise HTTPException(409, f"provider '{pid}' already exists")
        kind = body.kind or (preset.kind if preset else None)
        if kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {sorted(KINDS)}")
        base_url = body.base_url or (preset.base_url if preset else None)
        if not base_url or not re.match(r"^https?://", base_url):
            raise HTTPException(400, "base_url must be an http(s) URL")
        local = bool(preset.local) if preset else bool(re.match(r"^https?://(127\.0\.0\.1|localhost)", base_url))
        config = {
            "id": pid, "kind": kind, "name": body.name or (preset.name if preset else pid), "base_url": base_url,
            "model": body.model or (preset.example_model if preset else ""),
            "paid": body.paid if body.paid is not None else (preset.paid if preset else not local),
            "allow_paid": bool(body.allow_paid), "local": local, "preset": body.preset,
            "share_files": bool(body.share_files), "limits": body.limits.model_dump() if body.limits else {},
            "capabilities": body.capabilities if body.capabilities is not None else dict(preset.capabilities if preset else {}),
        }
        st().store.save_provider(config)
        if body.api_key:
            st().secrets.set(f"provider:{pid}", body.api_key)
        return st().public_provider(config)

    @app.patch("/api/providers/{pid}")
    async def patch_provider(pid: str, body: ProviderIn) -> dict:
        config = st().provider_config(pid)
        if not config:
            raise HTTPException(404, "provider not found")
        for key in ("name", "base_url", "model", "paid", "allow_paid", "share_files", "capabilities"):
            value = getattr(body, key)
            if value is not None:
                config[key] = value
        if body.limits is not None:
            config["limits"] = body.limits.model_dump()
        st().store.save_provider(config)
        if body.api_key is not None:
            if body.api_key:
                st().secrets.set(f"provider:{pid}", body.api_key)
            else:
                st().secrets.delete(f"provider:{pid}")
        st().invalidate_provider(pid)
        return st().public_provider(config)

    @app.delete("/api/providers/{pid}")
    async def delete_provider(pid: str) -> dict:
        if pid == "spike-local":
            raise HTTPException(400, "the built-in local provider cannot be removed")
        st().store.delete_provider(pid)
        st().secrets.delete(f"provider:{pid}")
        st().invalidate_provider(pid)
        return {"ok": True}

    @app.post("/api/providers/{pid}/test")
    async def test_provider(pid: str) -> dict:
        """Checks connectivity with the model list endpoint, which no supported provider bills for."""
        try:
            provider = st().provider(pid)
            models = await asyncio.wait_for(provider.list_models(), timeout=15)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}
        adapters = sorted(await st().refresh_adapters(pid))
        return {"ok": True, "models": models[:200], "adapters": adapters}

    # ---------------------------------------------------------------- call log and spending
    @app.get("/api/calls")
    async def calls(limit: int = 200, remote: bool = False) -> list[dict]:
        return st().store.calls(min(max(limit, 1), 2000), remote_only=remote)

    @app.delete("/api/calls")
    async def clear_calls() -> dict:
        st().store.clear_calls()
        return {"ok": True}

    @app.get("/api/usage")
    async def usage() -> list[dict]:
        return st().usage()

    # ---------------------------------------------------------------- settings
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return st().settings()

    @app.put("/api/settings")
    async def put_settings(patch: dict[str, Any]) -> dict:
        try:
            return st().update_settings(patch)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ---------------------------------------------------------------- projects
    def project_or_404(pid: str) -> dict:
        project = st().store.get_project(pid)
        if not project:
            raise HTTPException(404, "project not found")
        return project

    def check_mode(mode: str | None) -> None:
        if mode is not None and mode != "auto" and mode not in st().catalog.specialists:
            raise HTTPException(400, f"unknown mode '{mode}'")

    async def read_body(request: Request, limit: int) -> bytes:
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, f"the upload is limited to {limit // 1024**2} MB")
        data = await request.body()
        if len(data) > limit:
            raise HTTPException(413, f"the upload is limited to {limit // 1024**2} MB")
        return data

    @app.get("/api/projects")
    async def projects() -> list[dict]:
        return st().store.list_projects()

    @app.post("/api/projects")
    async def create_project(body: ProjectIn) -> dict:
        check_mode(body.mode)
        return st().store.create_project(body.name.strip(), body.instructions, body.mode)

    @app.post("/api/projects/import")
    async def import_project_zip(request: Request) -> dict:
        blob = await read_body(request, MAX_ARCHIVE_BYTES)
        try:
            project = import_project(st().store, st().project_files, blob, {"auto", *st().catalog.specialists})
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        for f in st().project_files.list(project["id"]):
            st().index_project_file(project["id"], f["path"])
        return project

    @app.get("/api/projects/{pid}")
    async def get_project(pid: str) -> dict:
        return project_or_404(pid)

    @app.patch("/api/projects/{pid}")
    async def patch_project(pid: str, body: ProjectPatch) -> dict:
        project_or_404(pid)
        check_mode(body.mode)
        return st().store.update_project(pid, **body.model_dump(exclude_none=True))

    @app.delete("/api/projects/{pid}")
    async def delete_project(pid: str) -> dict:
        project_or_404(pid)
        st().store.delete_project(pid)
        st().forget_project(pid)
        return {"ok": True}

    @app.get("/api/projects/{pid}/files")
    async def project_files(pid: str) -> list[dict]:
        project_or_404(pid)
        return st().project_files.list(pid)

    @app.put("/api/projects/{pid}/files/{path:path}")
    async def put_project_file(pid: str, path: str, request: Request) -> dict:
        project_or_404(pid)
        data = await read_body(request, MAX_FILE_BYTES)
        try:
            saved = st().project_files.write(pid, path, data)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**saved, "indexed": st().index_project_file(pid, saved["path"])}

    def existing_file(pid: str, path: str) -> Path:
        project_or_404(pid)
        try:
            target = st().project_files.path(pid, path)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not target.is_file():
            raise HTTPException(404, "file not found")
        return target

    @app.get("/api/projects/{pid}/files/{path:path}")
    async def get_project_file(pid: str, path: str):
        target = existing_file(pid, path)
        # a download, never a page: an uploaded .html must not run with the app's origin
        return FileResponse(target, media_type="application/octet-stream", filename=target.name,
                            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    @app.get("/api/workspace/files/{path:path}")
    async def get_workspace_file(path: str):
        """Files the tools wrote outside a project (documents, pages), offered as downloads."""
        try:
            target = Workspace(workspace_dir()).resolve(path)
        except PermissionError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not target.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(target, media_type="application/octet-stream", filename=target.name,
                            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    @app.delete("/api/projects/{pid}/files/{path:path}")
    async def delete_project_file(pid: str, path: str) -> dict:
        target = existing_file(pid, path)
        target.unlink()
        relative = target.relative_to(st().project_files.folder(pid)).as_posix()
        st().memory.store.delete_source(f"project:{pid}", f"file:{relative}")
        return {"ok": True}

    @app.get("/api/projects/{pid}/export")
    async def export_project_zip(pid: str) -> Response:
        project = project_or_404(pid)
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", project["name"]).strip("-") or "project"
        return Response(export_project(st().store, st().project_files, pid), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}.spike-project.zip"'})

    # ---------------------------------------------------------------- conversations
    @app.get("/api/conversations")
    async def conversations(project_id: str | None = None) -> list[dict]:
        return st().store.list_conversations(project_id=project_id)

    @app.post("/api/conversations")
    async def new_conversation(body: NewConversation | None = None) -> dict:
        project_id = body.project_id if body else None
        if project_id:
            project = project_or_404(project_id)
            return st().store.create_conversation(mode=project["mode"], project_id=project_id)
        return st().store.create_conversation()

    @app.get("/api/conversations/{cid}")
    async def get_conversation(cid: str) -> dict:
        conv = st().store.get_conversation(cid)
        if not conv:
            raise HTTPException(404, "conversation not found")
        return {**conv, "messages": st().store.messages(cid)}

    @app.patch("/api/conversations/{cid}")
    async def patch_conversation(cid: str, body: ConversationPatch) -> dict:
        conv = st().store.update_conversation(cid, **body.model_dump(exclude_none=True))
        if not conv:
            raise HTTPException(404, "conversation not found")
        return conv

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str) -> dict:
        st().store.delete_conversation(cid)
        return {"ok": True}

    # ---------------------------------------------------------------- memory
    def check_scope(scope: str) -> str:
        if scope != "global" and not (scope.startswith("project:") and st().store.get_project(scope[8:])):
            raise HTTPException(400, f"unknown memory scope '{scope}'")
        return scope

    @app.get("/api/memory")
    async def list_memory(scope: str | None = None, kind: str | None = None, q: str | None = None,
                          limit: int = 200) -> list[dict]:
        store = st().memory.store
        if q:
            scopes = [check_scope(scope)] if scope else ["global", *(f"project:{p['id']}" for p in st().store.list_projects())]
            vector, model = None, ""
            try:
                if (embedder := await st().memory.get_embedder()) is not None:
                    await st().memory.index()
                    vector, model = (await embedder.embed([q], query=True))[0], embedder.model
            except Exception:  # the embedding server is down or misbehaves: search by words only
                pass
            hits = store.search(q, scopes, vector, model, k=min(limit, 50), kinds=[kind] if kind else None)
            return [{**h.memory.public(), "match": h.text, "by": h.by} for h in hits]
        return [m.public() for m in store.list(scope=check_scope(scope) if scope else None, kind=kind, limit=limit)]

    @app.post("/api/memory")
    async def add_memory(body: MemoryIn) -> dict:
        try:
            memory = st().memory.store.add(body.text, body.kind, check_scope(body.scope), meta={"by": "user"})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        st().background(st().memory.index())
        return memory.public()

    @app.put("/api/memory/{mid}")
    async def update_memory(mid: str, body: MemoryPatch) -> dict:
        try:
            memory = st().memory.store.update(mid, body.text, body.kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if memory is None:
            raise HTTPException(404, "memory not found")
        st().background(st().memory.index())
        return memory.public()

    @app.delete("/api/memory/{mid}")
    async def delete_memory(mid: str) -> dict:
        if not st().memory.store.delete(mid):
            raise HTTPException(404, "memory not found")
        return {"ok": True}

    @app.delete("/api/memory")
    async def clear_memory(scope: str) -> dict:
        store = st().memory.store
        return {"deleted": store.clear() if scope == "all" else store.delete_scope(check_scope(scope))}

    @app.get("/api/memory-status")
    async def memory_status() -> dict:
        return st().memory_status()

    @app.get("/api/memory-export")
    async def export_memory(scope: str | None = None) -> Response:
        items = st().memory.store.export(check_scope(scope) if scope else None)
        return Response(json.dumps({"format": "spike-memory", "version": 1, "memories": items}, ensure_ascii=False,
                                   indent=1), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="spike-memory.json"'})

    @app.post("/api/memory-import")
    async def import_memory(request: Request) -> dict:
        try:
            data = json.loads(await read_body(request, 50 * 1024**2))
            items = data["memories"] if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise ValueError("expected a list of memories")
            for item in items:
                if isinstance(item, dict):
                    check_scope(str(item.get("scope") or "global"))
            added = st().memory.store.import_items(items)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, f"invalid memory file: {exc}") from exc
        st().background(st().memory.index())
        return {"imported": added}

    # ---------------------------------------------------------------- permissions
    @app.post("/api/permissions/{request_id}")
    async def decide(request_id: str, body: DecisionIn) -> dict:
        try:
            ok = st().broker.resolve(request_id, body.decision)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not ok:
            raise HTTPException(404, "no pending permission request with this id")
        return {"ok": True}

    # ---------------------------------------------------------------- runtime
    @app.get("/api/runtime")
    async def runtime_status() -> dict:
        rt = st().runtime
        return rt.status() if rt else {"running": False}

    @app.post("/api/runtime/start")
    async def runtime_start() -> dict:
        try:
            return await st().start_runtime()
        except (ValueError, FileNotFoundError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/runtime/stop")
    async def runtime_stop() -> dict:
        await st().stop_runtime()
        return {"running": False}

    # ---------------------------------------------------------------- chat
    @app.post("/api/chat")
    async def chat(body: ChatIn) -> StreamingResponse:
        state = st()
        if body.mode != "auto" and body.mode not in state.catalog.specialists:
            raise HTTPException(400, f"unknown mode '{body.mode}'")
        if body.provider_id and not state.provider_config(body.provider_id):
            raise HTTPException(400, f"unknown provider '{body.provider_id}'")
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(400, f"unknown project '{body.project_id}'")
        conv = state.store.get_conversation(body.conversation_id) if body.conversation_id else None
        if body.replace_from and conv is None:
            raise HTTPException(400, "replace_from needs an existing conversation")
        mode = body.mode
        if conv is None:
            project = state.store.get_project(body.project_id) if body.project_id else None
            if project and mode == "auto":
                mode = project["mode"]
            conv = state.store.create_conversation(title=_title_from(body.message), mode=mode,
                                                   provider_id=body.provider_id, project_id=body.project_id)
        project = state.store.get_project(conv["project_id"]) if conv.get("project_id") else None
        if body.replace_from:
            target = next((m for m in state.store.messages(conv["id"]) if m["id"] == body.replace_from), None)
            if target is None or target["role"] != "user":
                raise HTTPException(400, "replace_from must be a user message of this conversation")
            state.store.delete_messages_from(conv["id"], body.replace_from)
        history = [Message(role=m["role"], content=m["content"],
                           private=[m["content"]] if m["meta"].get("private") else [])  # answers that quote files
                   for m in state.store.messages(conv["id"]) if m["role"] in ("user", "assistant") and m["content"]]
        user_message = state.store.add_message(conv["id"], "user", body.message)
        await state.ensure_adapters(body.provider_id)
        await state.connectors.ensure_started()

        async def stream() -> AsyncIterator[bytes]:
            yield _sse({"type": "conversation", "id": conv["id"], "title": conv["title"],
                        "user_message_id": user_message["id"]})
            meta: dict[str, Any] = {"route": None, "plan": None, "subtasks": {}, "tools": [], "usage": []}
            final_text, error, cancelled = "", None, True
            orchestrator = state.orchestrator(body.provider_id, project_id=project["id"] if project else None)
            options = state.options(mode, project)
            try:
                if state.memory_settings()["enabled"]:
                    options.memory = await state.memory.recall(body.message, project["id"] if project else None)
                    if (memory_event := options.memory.event()) is not None:
                        meta["memory"] = memory_event
                        yield _sse(memory_event)
                async for ev in orchestrator.run(history, body.message, options):
                    kind = ev["type"]
                    if kind == "route":
                        meta["route"] = ev
                    elif kind == "plan":
                        meta["plan"] = ev
                    elif kind == "delta" and "subtask" in ev:
                        meta["subtasks"].setdefault(ev["subtask"], {"specialist": ev.get("specialist"), "text": ""})
                        meta["subtasks"][ev["subtask"]]["text"] += ev["text"]
                    elif kind in ("tool_call", "tool_result"):
                        meta["tools"].append(ev)
                    elif kind == "skill":
                        meta.setdefault("skills", []).extend(n for n in ev["names"] if n not in meta.get("skills", []))
                    elif kind == "usage":
                        meta["usage"].append(ev.get("usage"))
                    elif kind == "privacy":
                        seen = meta.setdefault("privacy", {})
                        seen[ev["provider"]] = max(seen.get(ev["provider"], 0), ev["withheld"])
                    elif kind == "done":
                        final_text, error = ev["text"], ev.get("error")
                        meta["elapsed_s"] = ev.get("elapsed_s")
                        if ev.get("private"):
                            meta["private"] = True
                        cancelled = False
                    yield _sse(ev)
            except Exception as exc:  # never leave the client hanging without a reason
                error, cancelled = f"{exc.__class__.__name__}: {exc}", False
                yield _sse({"type": "error", "message": error})
            finally:
                meta["error"] = error
                meta["cancelled"] = cancelled
                state.store.add_message(conv["id"], "assistant", final_text, meta)
                if not error and not cancelled:
                    state.background(state.maybe_summarize(conv["id"], body.provider_id))

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- web app
    static = static_dir()
    if static is not None:
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            target = (static / path).resolve()
            if path and target.is_file() and static in target.parents:
                return FileResponse(target)
            return FileResponse(static / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse({"message": "SPIKE API is running. The web UI is not built (cd web && npm run build)."})

    return app
