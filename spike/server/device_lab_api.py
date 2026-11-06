"""A21 Device Lab routes, local only. Running the checks and using adb are separate approvals in the request body
(`approved`, `android.approved`); without them nothing is started. One run at a time."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from spike.dev import device_lab as lab
from spike.dev.device_lab import AndroidRequest, DeviceLabError


class AndroidIn(BaseModel):
    serial: str = Field(default="", max_length=80)
    open_url: bool = True
    approved: bool = False

    def request(self) -> AndroidRequest:
        if self.serial and not lab.SERIAL.fullmatch(self.serial):
            raise HTTPException(400, "device_lab_android")
        return AndroidRequest(serial=self.serial, open_url=self.open_url)


class RunIn(BaseModel):
    url: str = Field(max_length=2000)
    profiles: list[str] | None = Field(default=None, max_length=lab.MAX_PROFILES)
    custom: list[dict[str, Any]] | None = Field(default=None, max_length=lab.MAX_CUSTOM)
    allow_hosts: list[str] = Field(default_factory=list, max_length=lab.MAX_ALLOW)
    approved: bool = False
    android: AndroidIn | None = None


class AndroidShotIn(AndroidIn):
    url: str = Field(max_length=2000)
    allow_hosts: list[str] = Field(default_factory=list, max_length=lab.MAX_ALLOW)


def refused(exc: DeviceLabError) -> HTTPException:
    return HTTPException(403 if exc.code == "device_lab_host" else 400, exc.code)


def create_device_lab_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter(prefix="/api/device-lab")
    busy = asyncio.Lock()

    async def exclusive(work: Callable[[], Any]) -> Any:
        """One browser run at a time, queued with the other heavy work (renders) so memory stays free."""
        if busy.locked():
            raise HTTPException(409, "device_lab_busy")
        async with busy:
            try:
                return await get_state().jobs.execute("render", work)
            except DeviceLabError as exc:
                raise refused(exc) from exc

    @router.get("")
    def status(request: Request) -> dict:
        """What can be chosen. Runs nothing: adb is only looked for on the PATH."""
        this_computer(request, "device_lab")
        return {"profiles": [p.to_dict() for p in lab.PROFILES], "limits": {"min_tap": lab.MIN_TAP, "min_font": lab.MIN_FONT,
                                                                           "custom": lab.MAX_CUSTOM},
                "browser": not lab.playwright_missing(), "adb": lab.adb_path() is not None}

    @router.get("/android")
    async def android(request: Request) -> dict:
        """What `adb devices` lists (it starts adb's own background server, as adb always does). No screenshot."""
        this_computer(request, "device_lab")
        return await lab.list_android()

    @router.post("/run")
    async def run(body: RunIn, request: Request) -> dict:
        this_computer(request, "device_lab")
        if not body.approved:
            raise HTTPException(403, "device_lab_approval")
        if body.android and not body.android.approved:
            raise HTTPException(403, "device_lab_android_approval")
        phone = body.android.request() if body.android else None
        try:
            lab.check_target(body.url, body.allow_hosts)
            lab.pick_profiles(body.profiles, body.custom)
        except DeviceLabError as exc:
            raise refused(exc) from exc

        async def work() -> dict:
            return await lab.run_device_lab(body.url, profiles=body.profiles, custom=body.custom,
                                            allow_hosts=body.allow_hosts, android=phone)

        return await exclusive(work)

    @router.post("/android")
    async def android_shot(body: AndroidShotIn, request: Request) -> dict:
        """Open the URL on a connected Android device and screenshot it; nothing else runs."""
        this_computer(request, "device_lab")
        if not body.approved:
            raise HTTPException(403, "device_lab_android_approval")

        async def work() -> dict:
            return await lab.android_shot(body.request(), lab.check_target(body.url, body.allow_hosts))

        return {"android": await exclusive(work)}

    return router
