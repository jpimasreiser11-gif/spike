"""SPIKE HTTP API (FastAPI) and static web app."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spike import __version__
from spike.core.types import Message
from spike.providers.registry import KINDS, PRESETS, PRESETS_BY_ID
from spike.runtime.hardware import detect, recommend
from spike.server.state import AppState


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
    capabilities: dict[str, Any] | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=200_000)
    conversation_id: str | None = None
    mode: str = "auto"
    provider_id: str | None = None


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


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(title="SPIKE", version=__version__)
    app.state.spike = state or AppState()

    def st() -> AppState:
        return app.state.spike

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
        for key in ("name", "base_url", "model", "paid", "allow_paid", "capabilities"):
            value = getattr(body, key)
            if value is not None:
                config[key] = value
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

    # ---------------------------------------------------------------- conversations
    @app.get("/api/conversations")
    async def conversations() -> list[dict]:
        return st().store.list_conversations()

    @app.post("/api/conversations")
    async def new_conversation() -> dict:
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
        conv = state.store.get_conversation(body.conversation_id) if body.conversation_id else None
        if conv is None:
            conv = state.store.create_conversation(title=_title_from(body.message), mode=body.mode,
                                                   provider_id=body.provider_id)
        history = [Message(role=m["role"], content=m["content"]) for m in state.store.messages(conv["id"])
                   if m["role"] in ("user", "assistant") and m["content"]]
        state.store.add_message(conv["id"], "user", body.message)
        for pid in state.providers_for_run(body.provider_id):
            if pid not in state.installed_adapters and state.provider_config(pid):
                await state.refresh_adapters(pid)

        async def stream() -> AsyncIterator[bytes]:
            yield _sse({"type": "conversation", "id": conv["id"], "title": conv["title"]})
            meta: dict[str, Any] = {"route": None, "plan": None, "subtasks": {}, "tools": [], "usage": []}
            final_text, error, cancelled = "", None, True
            orchestrator = state.orchestrator(body.provider_id)
            try:
                async for ev in orchestrator.run(history, body.message, state.options(body.mode)):
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
                    elif kind == "usage":
                        meta["usage"].append(ev.get("usage"))
                    elif kind == "done":
                        final_text, error = ev["text"], ev.get("error")
                        meta["elapsed_s"] = ev.get("elapsed_s")
                        cancelled = False
                    yield _sse(ev)
            except Exception as exc:  # never leave the client hanging without a reason
                error, cancelled = f"{exc.__class__.__name__}: {exc}", False
                yield _sse({"type": "error", "message": error})
            finally:
                meta["error"] = error
                meta["cancelled"] = cancelled
                state.store.add_message(conv["id"], "assistant", final_text, meta)

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
