"""SPIKE HTTP API (FastAPI) and static web app."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spike import __version__, creator
from spike.analytics.report import ReportError, build_docx, build_pdf, clean_blocks
from spike.connectors.apps import AppError
from spike.contracts import schema_error
from spike.core.types import Message
from spike.design.library import MAX_ZIP as MAX_DESIGN_BYTES
from spike.design.library import DesignError, preview_html
from spike.finance.backtest import STRATEGIES
from spike.finance.live import LiveError
from spike.finance.market import EXCHANGES
from spike.finance.paper import PaperError
from spike.forge.blueprint import from_user as blueprint_from_user
from spike.packs import MAX_BYTES as MAX_PACK_BYTES
from spike.packs import export_pack, install_skills_zip, read_pack
from spike.projects import MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, ProjectError, export_project, import_project
from spike.proof import build_proof
from spike.providers.guard import CURRENT_CHAT
from spike.providers.registry import KINDS, PRESETS, PRESETS_BY_ID
from spike.runtime.hardware import detect, recommend
from spike.runtime.paths import workspace_dir
from spike.server.mcp_server import PARSE_ERROR, SpikeMcp, rpc_error
from spike.server.openai_api import ApiError, check_access, create_router
from spike.server.openai_api import _is_loopback as _loopback
from spike.server.state import AppState
from spike.store.checkpoints import CheckpointError, RunCheckpoints
from spike.tools.builtin import Workspace
from spike.tools.documents import MissingLibrary

log = logging.getLogger(__name__)


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
    temporary: bool = False  # for a new chat: kept in memory only, no SPIKE memory read or written, gone on restart
    response_schema: dict[str, Any] | None = None  # answer contract: the answer is JSON following this JSON Schema
    forge: dict[str, Any] | None = None  # a Forge blueprint the user approved: the team runs it and checks it
    design_system: str | None = None  # a design system id; "none" for none; absent = the project's (Spike Design)
    view_context: list[dict[str, str]] | None = Field(default=None, max_length=4)  # MCP Apps: what views reported
    skills: list[str] | None = Field(default=None, max_length=3)  # skills chosen for this run (Creator templates)


class CreatorIn(BaseModel):
    template: str
    fields: dict[str, Any] = Field(default_factory=dict)
    lang: str = "es"


class BlueprintIn(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    provider_id: str | None = None
    project_id: str | None = None


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
    design: str = ""  # a design system id, or "" for none


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=100_000)
    mode: str | None = None
    design: str | None = None


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


class TuneIn(BaseModel):
    quick: bool = False


class LearnIn(BaseModel):
    action: Literal["save", "dismiss", "undo"]
    text: str | None = Field(default=None, max_length=2000)  # the user's wording of a proposed rule
    memory: str | None = None  # the memory to undo


class RouteIn(BaseModel):
    specialist: str  # the specialist the user retries this question with


class EvolutionItemPatch(BaseModel):
    status: Literal["proposed", "accepted", "rejected", "new", "ignored"] | None = None
    question: str | None = Field(default=None, max_length=4000)  # candidates
    checks: dict[str, list[str]] | None = None
    cause: str | None = Field(default=None, max_length=4000)  # failures
    fix: str | None = Field(default=None, max_length=4000)
    verified: bool | None = None


class BrowserIn(BaseModel):
    unknown: Literal["ask", "allow"]


class DomainIn(BaseModel):
    rule: Literal["allow", "deny"] | None  # None removes the domain's rule


class CheckIn(BaseModel):
    replay: bool = False  # also answer the accepted eval candidates again (runs the model)


class RollbackIn(BaseModel):
    component: str  # "router" or "adapter:<specialist>"


class UndoIn(BaseModel):
    force: bool = False  # also overwrite files that changed after the step


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)


class DecisionIn(BaseModel):
    decision: str


class BranchIn(BaseModel):
    before: str  # a user message: the new chat gets everything before it
    title: str | None = Field(default=None, max_length=300)


class LiveKeyIn(BaseModel):
    exchange: str
    api_key: str = Field(min_length=1, max_length=512)
    secret: str = Field(min_length=1, max_length=2048)


class LiveConfirmIn(BaseModel):
    id: str  # the order's id again, so a request without a body cannot confirm anything


class PaperResetIn(BaseModel):
    cash: float = Field(default=10_000, gt=0, le=1e12)
    quote: str = Field(default="USDT", pattern=r"^[A-Za-z0-9]{1,15}$")


class ViewCallIn(BaseModel):
    view: str = Field(pattern=r"^ui://", max_length=512)  # the view asking
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False  # the user allowed this call in the app


class ViewReadIn(BaseModel):
    view: str = Field(pattern=r"^ui://", max_length=512)
    uri: str = Field(min_length=1, max_length=2000)


class ViewEventIn(BaseModel):
    view: str = Field(pattern=r"^ui://", max_length=512)
    event: Literal["open-link", "message", "model-context", "log", "display-mode", "refused"]
    detail: str = Field(default="", max_length=4000)


class ConversationPatch(BaseModel):
    title: str | None = None
    mode: str | None = None
    provider_id: str | None = None


MAX_RUN_EVENTS = 3000  # events kept per answer for the step-by-step view
MAX_REPORT_BYTES = 40 * 1024**2  # an analysis report with its chart images


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


def view_context_text(items: list[dict[str, str]]) -> str:
    """What MCP App views asked to add to the model's context (`ui/update-model-context`), for this turn only."""
    parts = []
    for item in items[:4]:
        name = str(item.get("name") or item.get("view") or "app")[:100]
        text = str(item.get("text") or "").strip()[:4000]
        if text:
            parts.append(f"## {name}\n{text}")
    return "\n\n".join(parts)


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

    # ---------------------------------------------------------------- MCP server (Streamable HTTP, JSON answers)
    @app.post("/mcp", include_in_schema=False)
    async def mcp_endpoint(request: Request) -> Response:
        try:
            check_access(request)  # the /v1 rules: this computer only, or a token; never a web page without one
        except ApiError as exc:
            return exc.response()
        try:
            message = await request.json()
        except ValueError:
            return JSONResponse(rpc_error(None, PARSE_ERROR, "invalid JSON"), status_code=400)
        response = await SpikeMcp(st()).handle(message)
        return Response(status_code=202) if response is None else JSONResponse(response)

    @app.get("/mcp", include_in_schema=False)
    async def mcp_stream() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})  # no server-initiated messages

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

    # ---------------------------------------------------------------- design systems (Spike Design)
    def design_or_404(ds_id: str):
        ds = st().designs.get(ds_id)
        if ds is None:
            raise HTTPException(404, "design system not found")
        return ds

    @app.get("/api/design-systems")
    async def design_systems() -> list[dict]:
        return [d.to_dict() for d in st().designs.all()]

    @app.get("/api/design-systems/{ds_id}")
    async def design_system(ds_id: str) -> dict:
        return design_or_404(ds_id).to_dict(full=True)

    @app.get("/api/design-systems/{ds_id}/preview")
    async def design_preview(ds_id: str) -> dict:
        """A sample page in the system's tokens, for the app's isolated preview (not served as a page)."""
        return {"html": preview_html(design_or_404(ds_id))}

    @app.post("/api/design-systems/import")
    async def import_design(request: Request) -> dict:
        blob = await read_body(request, MAX_DESIGN_BYTES)
        try:
            imported = st().designs.import_blob(blob)
        except DesignError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"imported": [d.to_dict() for d in imported]}

    @app.delete("/api/design-systems/{ds_id}")
    async def delete_design(ds_id: str) -> dict:
        design_or_404(ds_id)
        try:
            st().designs.delete(ds_id)
        except DesignError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

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

    # MCP Apps: the app's iframe never calls these (its origin is opaque and its CSP blocks SPIKE); the app's own
    # code relays what the view asked for, after the user's approval where the tool's policy is "ask"
    @app.get("/api/connectors/{cid}/view")
    async def connector_view_page(cid: str, uri: str) -> dict:
        connector_view(cid)
        try:
            return await st().connectors.app_resource(cid, uri)
        except AppError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connectors/{cid}/view/call")
    async def connector_view_call(cid: str, body: ViewCallIn) -> dict:
        """{"result": CallToolResult}, or {"needs_approval": true} when the tool asks and the user has not allowed it."""
        connector_view(cid)
        try:
            return {"result": await st().connectors.app_call(cid, body.view, body.name, body.arguments, body.approved,
                                                             st().broker.policy_for_call)}
        except PermissionError as exc:
            if str(exc) == "needs your approval":
                return {"needs_approval": True}
            raise HTTPException(403, str(exc)) from exc
        except AppError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connectors/{cid}/view/read")
    async def connector_view_read(cid: str, body: ViewReadIn) -> dict:
        connector_view(cid)
        try:
            return await st().connectors.app_read(cid, body.view, body.uri)
        except AppError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connectors/{cid}/view/event")
    async def connector_view_event(cid: str, body: ViewEventIn) -> dict:
        """What a view did in the app (opened a link, wrote a message, gave context): kept in the audit log."""
        connector_view(cid)
        st().connectors.audit.write(connector=cid, view=body.view, event=body.event, detail=body.detail)
        return {"ok": True}

    @app.get("/api/connectors-audit")
    async def connectors_audit(limit: int = 100) -> list[dict]:
        return st().connectors.audit.tail(max(1, min(limit, 1000)))

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
    @app.get("/api/browser")
    async def browser_settings() -> dict:
        return st().connectors.browser_settings()

    @app.put("/api/browser")
    async def put_browser(body: BrowserIn) -> dict:
        """What the browser does on a domain without a rule: ask first, or open it."""
        return st().connectors.update_browser({"unknown": body.unknown})

    @app.put("/api/browser/domains/{domain}")
    async def browser_domain(domain: str, body: DomainIn) -> dict:
        """Allow or block a domain for the browser connector, or remove its rule."""
        try:
            return st().connectors.set_domain(domain, body.rule)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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

    # ---------------------------------------------------------------- tuning (`spike tune` from the app)
    @app.get("/api/tune")
    async def tune_report() -> dict | None:
        return st().tune_report()

    @app.post("/api/tune")
    async def run_tune(body: TuneIn) -> StreamingResponse:
        state = st()
        events = state.run_tune(quick=body.quick, tuner=getattr(app.state, "tuner", None))
        try:
            first = await events.__anext__()  # surfaces a missing model or a run in progress as an HTTP error
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

        async def stream() -> AsyncIterator[bytes]:
            yield _sse(first)
            try:
                async for ev in events:
                    yield _sse(ev)
            except Exception as exc:  # a failed llama-server start, for example
                yield _sse({"type": "error", "message": f"{exc.__class__.__name__}: {exc}"})

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

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
    async def put_settings(patch: dict[str, Any], request: Request) -> dict:
        if isinstance(patch.get("finance"), dict) and "live" in patch["finance"]:
            this_computer(request, "real-order settings")
        try:
            return st().update_settings(patch)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ---------------------------------------------------------------- finance
    def this_computer(request: Request, what: str) -> None:
        """Real orders are set up and confirmed only from this computer's browser: not from another machine on
        the network (`spike serve --host 0.0.0.0` has no login) and not from another web site."""
        client = request.client.host if request.client else ""
        if not _loopback(client):
            raise HTTPException(403, f"{what} can only be changed on the computer SPIKE runs on")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
            raise HTTPException(403, "request refused: it comes from another web site")

    def live_or_400(fn, *args):
        try:
            return fn(*args)
        except (LiveError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    async def paper_view() -> dict:
        fin = st().finance
        st_ = fin.paper.state()
        quote = st_["start"].get("quote", "USDT")
        symbols = {o["symbol"] for o in fin.paper.orders(status="open")} | \
            {f"{a}/{quote}" for a, q in st_["balances"].items() if q and a != quote}
        prices, error = {}, None
        for symbol in sorted(symbols):
            try:
                prices.update(await fin.prices({symbol}))
            except Exception as exc:  # offline: show the balances without a value
                error = str(exc)[:300]
        filled = fin.paper.refresh(prices)
        return {"valuation": fin.paper.valuation(prices), "balances": fin.paper.state()["balances"],
                "start": fin.paper.state()["start"], "orders": fin.paper.orders(limit=50), "just_filled": filled,
                "price_error": error}

    @app.get("/api/finance")
    async def finance_info() -> dict:
        fin = st().finance
        return {"settings": st().settings()["finance"], "exchanges": EXCHANGES, "strategies": STRATEGIES,
                "live": live_or_400(fin.live.status), "live_orders": fin.live.orders(20),
                "paper": {"balances": fin.paper.state()["balances"], "start": fin.paper.state()["start"]}}

    @app.get("/api/finance/paper")
    async def finance_paper() -> dict:
        return await paper_view()

    @app.post("/api/finance/paper/reset")
    async def finance_paper_reset(body: PaperResetIn) -> dict:
        try:
            st().finance.paper.reset(body.cash, body.quote)
        except PaperError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await paper_view()

    @app.post("/api/finance/paper/orders/{oid}/cancel")
    async def finance_paper_cancel(oid: str) -> dict:
        try:
            return st().finance.paper.cancel(oid)
        except PaperError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.put("/api/finance/live/key")
    async def finance_live_key(body: LiveKeyIn, request: Request) -> dict:
        this_computer(request, "exchange keys")
        live_or_400(st().finance.live.set_key, body.exchange, body.api_key, body.secret)
        return live_or_400(st().finance.live.status)  # never the key itself

    @app.delete("/api/finance/live/key/{exchange}")
    async def finance_live_key_delete(exchange: str, request: Request) -> dict:
        this_computer(request, "exchange keys")
        st().finance.live.delete_key(exchange)
        return live_or_400(st().finance.live.status)

    @app.post("/api/finance/live/check")
    async def finance_live_check(request: Request) -> dict:
        this_computer(request, "exchange keys")
        try:
            result = await st().finance.live.check_key()
        except (LiveError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**result, "status": st().finance.live.status()}

    @app.get("/api/finance/live/orders")
    async def finance_live_orders() -> list[dict]:
        return st().finance.live.orders(50)

    @app.get("/api/finance/live/orders/{oid}")
    async def finance_live_order(oid: str) -> dict:
        try:
            return st().finance.live.get(oid)
        except LiveError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/finance/live/orders/{oid}/confirm")
    async def finance_live_confirm(oid: str, body: LiveConfirmIn, request: Request) -> dict:
        """The user's click on a proposed real order: the only way one reaches the exchange."""
        this_computer(request, "real orders")
        if request.headers.get("x-spike-confirm") != oid or body.id != oid:
            raise HTTPException(400, "a confirmation must name the order in the body and the X-Spike-Confirm header")
        try:
            return await st().finance.live.confirm(oid)
        except (LiveError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/finance/live/orders/{oid}/cancel")
    async def finance_live_cancel(oid: str) -> dict:
        try:
            return st().finance.live.cancel(oid)
        except LiveError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ---------------------------------------------------------------- analytics
    @app.post("/api/analytics/report")
    async def analytics_report(request: Request) -> Response:
        """An analysis from the chat as a Word or PDF file (the app renders the charts as PNG)."""
        try:
            body = json.loads(await read_body(request, MAX_REPORT_BYTES))
            fmt = body.get("format")
            if fmt not in ("docx", "pdf"):
                raise ReportError("format must be docx or pdf")
            title = str(body.get("title") or "Informe de datos").strip()[:200] or "Informe de datos"
            blocks = clean_blocks(body.get("blocks"))
            data = (build_docx if fmt == "docx" else build_pdf)(title, blocks)
        except (ReportError, json.JSONDecodeError, AttributeError) as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, ReportError) else "invalid report") from exc
        except MissingLibrary as exc:
            raise HTTPException(501, str(exc).removeprefix("error: ")) from exc
        slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore")
                      .decode()).strip("-")[:60] or "informe"
        media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" if fmt == "docx"
                 else "application/pdf")
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{slug}.{fmt}"',
                                                         "X-Content-Type-Options": "nosniff"})

    # ---------------------------------------------------------------- projects
    def project_or_404(pid: str) -> dict:
        project = st().store.get_project(pid)
        if not project:
            raise HTTPException(404, "project not found")
        return project

    def check_design(ds_id: str | None) -> None:
        if ds_id and st().designs.get(ds_id) is None:
            raise HTTPException(400, f"unknown design system '{ds_id}'")

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
        check_design(body.design)
        return st().store.create_project(body.name.strip(), body.instructions, body.mode, body.design)

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
        check_design(body.design)
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
        store = st().store_for(cid)
        conv = store.get_conversation(cid)
        if not conv:
            raise HTTPException(404, "conversation not found")
        return {**conv, "messages": store.messages(cid), "temporary": store is st().temp}

    @app.patch("/api/conversations/{cid}")
    async def patch_conversation(cid: str, body: ConversationPatch) -> dict:
        conv = st().store_for(cid).update_conversation(cid, **body.model_dump(exclude_none=True))
        if not conv:
            raise HTTPException(404, "conversation not found")
        return conv

    @app.get("/api/conversations/{cid}/proof")
    async def proof_package(cid: str) -> Response:
        """The chat with every recorded step, its model calls and file checksums, as a verifiable zip."""
        state = st()
        store = state.store_for(cid)
        conv = store.get_conversation(cid)
        if not conv:
            raise HTTPException(404, "conversation not found")
        data = build_proof(conv, store.messages(cid), state.store.calls_for(cid), state.store.list_checkpoints(cid),
                           state.provider_configs(), state.settings(), temporary=store is state.temp)
        ascii_title = unicodedata.normalize("NFKD", conv["title"]).encode("ascii", "ignore").decode()
        name = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:40] or "chat"  # headers are ASCII
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="spike-proof-{name}-{time.strftime("%Y%m%d")}.zip"'})

    @app.post("/api/conversations/{cid}/branch")
    async def branch_conversation(cid: str, body: BranchIn) -> dict:
        """A copy of the chat up to (not including) one of the user's messages, so an edit can go on in its own
        chat and the original stays as it was. Undo stays with the original chat's steps."""
        store = st().store_for(cid)
        conv = store.get_conversation(cid)
        if not conv:
            raise HTTPException(404, "conversation not found")
        messages = store.messages(cid)
        at = next((i for i, m in enumerate(messages) if m["id"] == body.before and m["role"] == "user"), None)
        if at is None:
            raise HTTPException(400, "'before' must be a user message of this conversation")
        new = store.create_conversation(title=body.title or conv["title"], mode=conv["mode"],
                                        provider_id=conv["provider_id"], project_id=conv["project_id"])
        for m in messages[:at]:
            meta = json.loads(json.dumps(m["meta"]))
            for ev in [*(meta.get("tools") or []), *(meta.get("events") or [])]:
                ev.pop("checkpoint", None)
            meta.pop("learn", None)
            store.add_message(new["id"], m["role"], m["content"], meta, created=m["created"])
        return {**new, "temporary": store is st().temp}

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str) -> dict:
        st().store_for(cid).delete_conversation(cid)
        st().checkpoints.delete_conversation(cid)
        return {"ok": True}

    @app.post("/api/checkpoints/{cp_id}/undo")
    async def undo_step(cp_id: str, body: UndoIn) -> dict:
        """Put back the files one tool call changed, and mark that step as undone in its chat."""
        state = st()
        try:
            cp = state.checkpoints.undo(cp_id, force=body.force)
        except CheckpointError as exc:
            raise HTTPException(exc.status, {"message": str(exc), "changed": exc.changed}) from exc
        store = state.store_for(cp["conversation_id"])
        for m in store.messages(cp["conversation_id"]):
            events = m["meta"].get("tools") or []
            hit = [ev for ev in events if ev.get("type") == "tool_result" and ev.get("checkpoint") == cp_id]
            for ev in hit + [ev for ev in m["meta"].get("events") or [] if ev.get("checkpoint") == cp_id]:
                ev["undone"] = True
            if hit:
                store.update_message_meta(m["id"], m["meta"])
        return {"ok": True, "files": [f["path"] for f in cp["files"]]}

    @app.post("/api/messages/{mid}/learn")
    async def learn(mid: str, body: LearnIn) -> dict:
        """Save, reword or dismiss the rule proposed from a correction, or undo what a message saved to memory."""
        try:
            return st().apply_learning(mid, body.action, body.text, body.memory)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/messages/{mid}/route")
    async def route_correction(mid: str, body: RouteIn) -> dict:
        """The user retries this question with another specialist: a route correction the router learns from."""
        try:
            return st().route_correction(mid, body.specialist)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ---------------------------------------------------------------- evolution
    @app.get("/api/evolution")
    async def evolution() -> dict:
        state = st()
        return {"settings": state.evolution_settings(), **state.evolution.overview(state.base_catalog())}

    @app.get("/api/evolution/items")
    async def evolution_items(kind: str | None = None, status: str | None = None) -> list[dict]:
        return st().evolution.store.items(kind, status)

    @app.patch("/api/evolution/items/{iid}")
    async def patch_evolution_item(iid: str, body: EvolutionItemPatch) -> dict:
        evo = st().evolution
        item = evo.store.get(iid)
        if item is None:
            raise HTTPException(404, "item not found")
        try:
            if item["kind"] == "failure":
                return evo.update_failure(iid, cause=body.cause, fix=body.fix, verified=body.verified)
            if item["kind"] == "candidate":
                return evo.review_candidate(iid, body.status, body.question, body.checks)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if item["kind"] == "route" and body.status in ("new", "ignored"):
            return evo.store.update(iid, status=body.status)
        raise HTTPException(400, f"a {item['kind']} cannot be changed this way")

    @app.delete("/api/evolution/items/{iid}")
    async def delete_evolution_item(iid: str) -> dict:
        if not st().evolution.store.delete(iid):
            raise HTTPException(404, "item not found")
        return {"ok": True}

    @app.get("/api/evolution/items/{iid}/issue")
    async def failure_issue(iid: str) -> Response:
        item = st().evolution.store.get(iid)
        if item is None or item["kind"] != "failure":
            raise HTTPException(404, "failure not found")
        return Response(st().evolution.issue_markdown(item), media_type="text/markdown; charset=utf-8")

    @app.get("/api/evolution/candidates.jsonl")
    async def export_candidates() -> Response:
        return Response(st().evolution.export(), media_type="application/x-ndjson",
                        headers={"Content-Disposition": 'attachment; filename="spike-eval-candidates.jsonl"'})

    @app.post("/api/evolution/router/learn")
    async def learn_router() -> dict:
        return st().learn_router()

    @app.post("/api/evolution/check")
    async def evolution_check(body: CheckIn) -> dict:
        from spike.evolution.checks import run_checks

        return await run_checks(st(), replay=body.replay)

    @app.post("/api/evolution/rollback")
    async def evolution_rollback(body: RollbackIn) -> dict:
        state = st()
        try:
            previous = state.rollback(body.component)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from exc
        restarted = False
        if body.component.startswith("adapter:") and state.runtime and state.runtime.running():
            await state.start_runtime()  # llama-server loads adapters when it starts
            restarted = True
        return {"active": previous, "restarted": restarted}

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

    @app.post("/api/questions/{question_id}")
    async def answer_question(question_id: str, body: AnswerIn) -> dict:
        """The user's answer to a question a specialist asked with `ask_user`; the paused run goes on with it."""
        if not st().broker.answer(question_id, body.answer.strip()):
            raise HTTPException(404, "no pending question with this id")
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

    # ---------------------------------------------------------------- creator
    @app.get("/api/creator/templates")
    async def creator_templates(lang: str = "es") -> list[dict]:
        return creator.templates(lang)

    @app.get("/api/creator/data-files")
    async def creator_data_files(project_id: str | None = None) -> list[dict]:
        if project_id:
            project_or_404(project_id)
        return creator.data_files(st().project_files.folder(project_id) if project_id else workspace_dir())

    @app.post("/api/creator/blueprint")
    async def creator_blueprint(body: CreatorIn) -> dict:
        """A template filled with the user's answers: a Forge blueprint to review, its skills and design flag."""
        try:
            return creator.build(body.template, body.fields, body.lang)
        except (creator.CreatorError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    # ---------------------------------------------------------------- forge
    @app.post("/api/forge/blueprint")
    async def forge_blueprint(body: BlueprintIn) -> dict:
        """Draft a Forge blueprint for the user to review and approve; nothing runs yet."""
        state = st()
        if body.provider_id and not state.provider_config(body.provider_id):
            raise HTTPException(400, f"unknown provider '{body.provider_id}'")
        if body.project_id and not state.store.get_project(body.project_id):
            raise HTTPException(400, f"unknown project '{body.project_id}'")
        await state.ensure_adapters(body.provider_id)
        return (await state.blueprint(body.task, body.provider_id, body.project_id)).to_dict()

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
        store = state.store_for(body.conversation_id) if body.conversation_id else \
            state.temp if body.temporary else state.store
        temporary = store is state.temp
        conv = store.get_conversation(body.conversation_id) if body.conversation_id else None
        if body.replace_from and conv is None:
            raise HTTPException(400, "replace_from needs an existing conversation")
        if body.response_schema is not None and (problem := schema_error(body.response_schema)) is not None:
            raise HTTPException(400, problem)
        if body.design_system and body.design_system != "none":
            check_design(body.design_system)
        if unknown := [n for n in body.skills or [] if state.skills.get(n) is None]:
            raise HTTPException(400, f"unknown skill '{unknown[0]}'")
        blueprint = None
        if body.forge is not None:
            if body.response_schema is not None:
                raise HTTPException(400, "a Forge task cannot also have an answer contract")
            try:
                blueprint = blueprint_from_user(body.forge, state.catalog)
            except ValueError as exc:
                raise HTTPException(400, f"blueprint: {exc}") from exc
            if blueprint.deliverables and not state.settings()["tools_enabled"]:
                raise HTTPException(400, "this blueprint saves files, which needs tools: turn them on in Settings")
        mode = body.mode
        if conv is None:
            project = state.store.get_project(body.project_id) if body.project_id else None
            if project and mode == "auto":
                mode = project["mode"]
            conv = store.create_conversation(title=_title_from(body.message), mode=mode,
                                                   provider_id=body.provider_id, project_id=body.project_id)
        project = state.store.get_project(conv["project_id"]) if conv.get("project_id") else None
        if body.replace_from:
            target = next((m for m in store.messages(conv["id"]) if m["id"] == body.replace_from), None)
            if target is None or target["role"] != "user":
                raise HTTPException(400, "replace_from must be a user message of this conversation")
            store.delete_messages_from(conv["id"], body.replace_from)
        history = [Message(role=m["role"], content=m["content"],
                           private=[m["content"]] if m["meta"].get("private") else [])  # answers that quote files
                   for m in store.messages(conv["id"]) if m["role"] in ("user", "assistant") and m["content"]]
        user_message = store.add_message(conv["id"], "user", body.message)
        await state.ensure_adapters(body.provider_id)
        await state.connectors.ensure_started()

        async def stream() -> AsyncIterator[bytes]:
            CURRENT_CHAT.set(conv["id"])  # the call log notes which chat each model call was for
            yield _sse({"type": "conversation", "id": conv["id"], "title": conv["title"],
                        "user_message_id": user_message["id"], **({"temporary": True} if temporary else {})})
            meta: dict[str, Any] = {"route": None, "plan": None, "subtasks": {}, "tools": [], "usage": []}
            final_text, error, cancelled = "", None, True
            orchestrator = state.orchestrator(body.provider_id, project_id=project["id"] if project else None)
            options = state.options(mode, project)
            options.checkpoints = RunCheckpoints(state.checkpoints, conv["id"])
            options.json_schema = body.response_schema
            options.forge = blueprint
            options.skills = list(body.skills or [])
            if body.design_system is not None:  # the chat's choice replaces the project's
                options.design = state.designs.get(body.design_system)
            if options.design is not None:
                meta["design"] = {"id": options.design.id, "name": options.design.name}
            if body.view_context:
                options.view_context = view_context_text(body.view_context)
                meta["view_context"] = [str(v.get("name") or v.get("view") or "")[:100] for v in body.view_context]
            if blueprint is not None:
                meta["forge"] = {"blueprint": blueprint.to_dict()}
            started = time.perf_counter()

            def record(ev: dict[str, Any]) -> None:
                """The run's events, for the step-by-step view; consecutive text pieces are merged."""
                events = meta.setdefault("events", [])
                last = events[-1] if events else None
                if (ev["type"] in ("delta", "reasoning") and last and last["type"] == ev["type"]
                        and last.get("subtask") == ev.get("subtask")):
                    last["text"] += ev["text"]
                elif len(events) < MAX_RUN_EVENTS:
                    events.append({**ev, "t": round(time.perf_counter() - started, 3)})
            try:
                if "design" in meta:  # the answer's design system, shown as a chip
                    design_event = {"type": "design", **meta["design"]}
                    record(design_event)
                    yield _sse(design_event)
                learned, saved = ({}, []) if temporary else state.learn_from(
                    body.message, conv, user_message["id"], any(m.role == "assistant" for m in history))
                if learned:
                    meta["learn"] = learned
                    for ev in ([{"type": "memory_saved", "saved": learned["saved"]}] if "saved" in learned else
                               [{"type": "correction", "text": learned["correction"]["text"]}]):
                        record(ev)
                        yield _sse(ev)
                if state.memory_settings()["enabled"] and not temporary:
                    options.memory = await state.memory.recall(body.message, project["id"] if project else None)
                    options.memory.saved = saved
                    if (memory_event := options.memory.event()) is not None:
                        meta["memory"] = memory_event
                        record(memory_event)
                        yield _sse(memory_event)
                async for ev in orchestrator.run(history, body.message, options):
                    kind = ev["type"]
                    if kind == "route":
                        meta["route"] = ev
                    elif kind == "plan":
                        meta["plan"] = ev
                    elif kind == "subtask_start":
                        meta["subtasks"].setdefault(ev["subtask"], {"specialist": ev.get("specialist"), "text": "",
                                                                    "role": ev.get("role"), "round": ev.get("round"),
                                                                    "task": ev.get("task")})
                    elif kind == "verify":
                        meta.setdefault("verify", []).append({k: v for k, v in ev.items() if k != "type"})
                    elif kind == "forge_report":
                        meta.setdefault("forge", {})["report"] = {k: v for k, v in ev.items() if k != "type"}
                    elif kind == "delta" and "subtask" in ev:
                        meta["subtasks"].setdefault(ev["subtask"], {"specialist": ev.get("specialist"), "text": ""})
                        meta["subtasks"][ev["subtask"]]["text"] += ev["text"]
                    elif kind in ("tool_call", "tool_result"):
                        meta["tools"].append(ev)
                    elif kind == "skill":
                        meta.setdefault("skills", []).extend(n for n in ev["names"] if n not in meta.get("skills", []))
                    elif kind == "usage":
                        meta["usage"].append(ev.get("usage"))
                    elif kind == "contract":
                        meta["contract"] = {k: ev[k] for k in ("valid", "attempts", "errors")}
                    elif kind == "question":
                        meta.setdefault("questions", []).append(
                            {k: ev[k] for k in ("id", "question", "options") if k in ev})
                    elif kind == "answered":
                        for q in meta.get("questions", []):
                            if q["id"] == ev["id"]:
                                q["answer"] = ev["answer"]
                    elif kind == "privacy":
                        seen = meta.setdefault("privacy", {})
                        seen[ev["provider"]] = max(seen.get(ev["provider"], 0), ev["withheld"])
                    elif kind == "done":
                        final_text, error = ev["text"], ev.get("error")
                        meta["elapsed_s"] = ev.get("elapsed_s")
                        if ev.get("private"):
                            meta["private"] = True
                        cancelled = False
                    record(ev)
                    yield _sse(ev)
            except Exception as exc:  # never leave the client hanging without a reason
                error, cancelled = f"{exc.__class__.__name__}: {exc}", False
                yield _sse({"type": "error", "message": error})
            finally:
                meta["error"] = error
                meta["cancelled"] = cancelled
                answer = store.add_message(conv["id"], "assistant", final_text, meta)
                if not temporary and state.evolution_settings()["enabled"]:
                    try:
                        state.evolution.record_failures(body.message, meta, conv["id"], answer["id"])
                    except Exception as exc:  # recording a failure must never become one
                        log.warning("evolution: could not record a failure: %s", exc)
                if not error and not cancelled and not temporary:
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
