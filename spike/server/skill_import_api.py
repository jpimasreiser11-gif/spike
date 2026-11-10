"""Install a skill from a GitHub URL, with review (O3). Two routes, both only for this computer's own browser and
only on a person's button press: nothing here is a model tool, and nothing installs on a model's suggestion.

1. POST /api/skills/import-github/preview {url}: downloads the repository's ZIP, validates it in memory and returns the
   license, SKILL.md and every file with its size (text for text files, a flag for binaries). Nothing is written.
2. POST /api/skills/import-github/install {preview_id, sha256}: installs exactly the reviewed bytes, DISABLED. The hash
   must be the preview's own; a skill whose license is not on the allow-list, or that fails validation, is refused.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from spike.server.backup_api import local_only
from spike.skills import github_import as gi

PREVIEW_TTL = 900  # seconds a preview can be installed
MAX_PREVIEWS = 5


class PreviewIn(BaseModel):
    url: str = Field(max_length=600)


class InstallIn(BaseModel):
    preview_id: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


def create_skill_import_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter()
    previews: dict[str, tuple[float, gi.Preview]] = {}
    lock = asyncio.Lock()

    def fail(exc: gi.ImportFail) -> HTTPException:
        return HTTPException(exc.status, exc.code)

    def prune() -> None:
        now = time.monotonic()
        for key in [k for k, (at, _) in previews.items() if now - at > PREVIEW_TTL]:
            del previews[key]
        while len(previews) >= MAX_PREVIEWS:
            del previews[min(previews, key=lambda k: previews[k][0])]

    async def read_body(request: Request, model: type[BaseModel]) -> Any:
        """Origin, client and content type are checked before the body is even parsed."""
        local_only(request, {"application/json"})
        try:
            return model.model_validate(await request.json())
        except (ValidationError, ValueError):
            raise HTTPException(422, "invalid_request") from None

    @router.post("/api/skills/import-github/preview")
    async def preview(request: Request) -> dict:
        body = await read_body(request, PreviewIn)
        try:
            ref = gi.parse_github_url(body.url)
            blob = await gi.download_zip(ref)
            result = await asyncio.to_thread(gi.build_preview, blob, ref)
        except gi.ImportFail as exc:
            raise fail(exc) from None
        async with lock:
            prune()
            preview_id = secrets.token_urlsafe(18)
            previews[preview_id] = (time.monotonic(), result)
        return {"preview_id": preview_id, **result.public()}

    @router.post("/api/skills/import-github/install")
    async def install(request: Request) -> dict:
        body = await read_body(request, InstallIn)
        st = get_state()
        async with lock:
            prune()
            entry = previews.get(body.preview_id)
            if entry is None:
                raise HTTPException(404, "preview_expired")
            result = entry[1]
            if not hmac.compare_digest(body.sha256.lower(), result.sha256) or gi.digest(result.files) != result.sha256:
                raise HTTPException(400, "hash_mismatch")
            if not result.license["can_enable"]:
                raise HTTPException(403, "license_blocked")
            if not result.can_install:
                raise HTTPException(400, "invalid_skill")
            if st.skills.get(result.name) is not None:
                raise HTTPException(409, "exists")
            # disabled first, so the skill is never enabled for a moment
            disabled = [n for n in st.settings()["disabled_skills"] if n != result.name] + [result.name]
            st.update_settings({"disabled_skills": disabled})
            try:
                await asyncio.to_thread(gi.install_files, result, st.home / "skills")
            except gi.ImportFail as exc:
                raise fail(exc) from None
            del previews[body.preview_id]
        st.skills.reload()
        return {"name": result.name, "enabled": False, "license": result.license["id"]}

    return router
