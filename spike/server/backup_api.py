"""Backup, restore and "delete all my data" (G34, G36). Every route works only from this computer's browser: a loopback
client, no other site's Origin, and a body type a plain cross-site form cannot send (ZIP uploads and JSON).

A restore or a deletion closes SPIKE's state (databases, MCP servers, background jobs), changes the files, and opens
a fresh state on the same home, so nothing writes to a database while it is being replaced or removed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets as pyrandom
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from spike import backup, wipe
from spike.finance.live import key_names
from spike.finance.market import EXCHANGES
from spike.server.openai_api import _is_loopback
from spike.server.state import AppState

ZIP_TYPES = {"application/zip", "application/x-zip-compressed", "application/octet-stream"}
WORD_TTL = 600  # seconds a confirmation word stays valid
WORDS = {"es": "BORRAR", "en": "DELETE"}


class DeleteIn(BaseModel):
    word: str = Field(min_length=1, max_length=40)
    delete_models: bool = False
    delete_secrets: bool = False


def local_only(request: Request, types: set[str] | None = None) -> None:
    client = request.client.host if request.client else ""
    if not _is_loopback(client):
        raise HTTPException(403, "your data can only be exported or deleted on the computer SPIKE runs on")
    origin = request.headers.get("origin")
    if (origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()) or \
            request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "request refused: it comes from another web site")
    if types is not None and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in types:
        raise HTTPException(415, "unsupported content type")


def secret_names(state: AppState) -> list[str]:
    """Every key name SPIKE stores, so they can be removed from the OS keychain too (it cannot be listed)."""
    names = [f"provider:{p['id']}" for p in state.store.list_providers() if p.get("id")]
    with contextlib.suppress(Exception):
        names += [f"connector:{d.id}:{s['name']}" for d in state.connectors.definitions() for s in d.secrets]
    names += [n for ex in EXCHANGES for n in key_names(ex)]
    return list(dict.fromkeys(names))


def remembered_names(home: Path) -> list[str]:
    try:
        raw = json.loads((home / wipe.NAMES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [n for n in raw if isinstance(n, str)][:10_000] if isinstance(raw, list) else []


def _close_databases(state: AppState) -> None:
    for close in (lambda: state.store._conn.close(), state.memory.store.close,
                  lambda: state.evolution.store._conn.close()):
        with contextlib.suppress(Exception):
            close()


def create_backup_router(get_state: Callable[[], AppState]) -> APIRouter:
    router = APIRouter()
    lock = asyncio.Lock()
    words: dict[str, float] = {}

    async def spool(request: Request) -> tempfile.SpooledTemporaryFile:
        try:
            if int(request.headers.get("content-length") or 0) > backup.MAX_BYTES:
                raise HTTPException(413, "the backup is too large")
        except ValueError as exc:
            raise HTTPException(400, "invalid Content-Length header") from exc
        f = tempfile.SpooledTemporaryFile(max_size=64 * 1024**2)  # noqa: SIM115 (the caller closes it)
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > backup.MAX_BYTES:
                f.close()
                raise HTTPException(413, "the backup is too large")
            f.write(chunk)
        f.seek(0)
        return f

    async def reopened(request: Request, work: Callable[[AppState], dict]) -> dict:
        """Runs `work` with SPIKE's state closed, then opens a new state on the same home."""
        old = get_state()
        await old.close()
        _close_databases(old)
        try:
            return await asyncio.to_thread(work, old)
        finally:
            request.app.state.spike = AppState(home=old.home, provider_factory=old.provider_factory,
                                               market_factory=old.finance.market.factory)
            with contextlib.suppress(AttributeError, KeyError):
                del request.app.state.model_setup  # the launcher's setup service held the old state

    @router.get("/api/backup/export")
    async def export(request: Request, include_models: bool = False) -> StreamingResponse:
        local_only(request)
        out = tempfile.TemporaryFile()  # noqa: SIM115 (closed by the response stream)
        try:
            await asyncio.to_thread(backup.create_backup, get_state().home, out, include_models)
        except backup.BackupError as exc:
            out.close()
            raise HTTPException(500, str(exc)) from exc
        out.seek(0)

        def chunks():
            with out:
                while chunk := out.read(backup.CHUNK):
                    yield chunk

        name = f"spike-backup-{time.strftime('%Y%m%d-%H%M')}.zip"
        return StreamingResponse(chunks(), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.post("/api/backup/preview")
    async def preview(request: Request) -> dict:
        local_only(request, ZIP_TYPES)
        with await spool(request) as f:
            try:
                return await asyncio.to_thread(backup.inspect_backup, f, get_state().home)
            except backup.BackupError as exc:
                raise HTTPException(400, str(exc)) from exc

    @router.post("/api/backup/restore")
    async def restore(request: Request, overwrite: bool = False) -> dict:
        """Adds what is missing; replaces existing files only with `overwrite=1` (the UI asks first)."""
        local_only(request, ZIP_TYPES)
        async with lock:
            with await spool(request) as f:
                try:  # verified completely before SPIKE's state is closed
                    await asyncio.to_thread(backup.inspect_backup, f, get_state().home)
                except backup.BackupError as exc:
                    raise HTTPException(400, str(exc)) from exc
                f.seek(0)
                try:
                    return await reopened(request, lambda st: backup.restore_backup(f, st.home, overwrite))
                except backup.BackupError as exc:
                    raise HTTPException(400, str(exc)) from exc

    @router.get("/api/privacy/delete-word")
    async def delete_word(request: Request, lang: str = "en") -> dict:
        """The word the user must type to confirm deleting everything; single use, valid for 10 minutes."""
        local_only(request)
        now = time.time()
        for w in [w for w, t in words.items() if t < now]:
            words.pop(w)
        word = f"{WORDS.get(lang, WORDS['en'])}-{pyrandom.randbelow(9000) + 1000}"
        words[word] = now + WORD_TTL
        while len(words) > 8:
            words.pop(next(iter(words)))
        return {"word": word, "expires_in": WORD_TTL}

    @router.post("/api/privacy/delete")
    async def delete_all(request: Request) -> dict:
        local_only(request, {"application/json"})  # checked before the body is read
        try:
            body = DeleteIn.model_validate_json(await request.body())
        except ValidationError as exc:
            raise HTTPException(422, "send a JSON object with the confirmation word") from exc
        async with lock:
            if words.pop(body.word.strip(), 0) < time.time():
                raise HTTPException(400, "the confirmation word does not match; ask for a new one")
            try:  # before anything is closed or any key is removed
                wipe.check_home(get_state().home)
            except ValueError as exc:  # the reason (which folder) stays in the exception; the user gets one sentence
                raise HTTPException(409, "refused: this is not SPIKE's own data folder") from exc

            def work(st: AppState) -> dict:
                removed_keys = 0
                if body.delete_secrets:
                    for name in names:
                        with contextlib.suppress(Exception):
                            if st.secrets.has(name):
                                st.secrets.delete(name)
                                removed_keys += 1
                else:  # the database that named the keys goes: keep the names (never the values) to delete them later
                    with contextlib.suppress(Exception):
                        kept = [n for n in names if st.secrets.has(n)]
                        (st.home / wipe.NAMES_FILE).write_text(json.dumps(kept), encoding="utf-8")
                result = wipe.delete_everything(st.home, body.delete_models, body.delete_secrets)
                return result | {"secrets_deleted": body.delete_secrets, "keys_removed": removed_keys,
                                 "models_deleted": body.delete_models}

            state = get_state()
            names = list(dict.fromkeys(secret_names(state) + remembered_names(state.home)))
            return await reopened(request, work)

    return router
