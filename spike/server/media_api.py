"""Local-only speech routes. Saving the opt-in and clicking a speech action authorize that command only."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from spike.media import DEFAULTS, MAX_AUDIO, MediaError, Speech
from spike.runtime.paths import workspace_dir


class SpeechSettings(BaseModel):
    enabled: bool = False
    whisper_model: str = Field(default='', max_length=1000)
    piper_model: str = Field(default='', max_length=1000)
    piper_license: str = Field(default='', max_length=1000)


class AudioIn(BaseModel):
    audio: str = Field(max_length=MAX_AUDIO * 4 // 3 + 4)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


def create_media_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter(prefix='/api/media')
    lock = asyncio.Lock()

    def service() -> Speech:
        return Speech(workspace_dir(), get_state().store.get_setting('speech', dict(DEFAULTS)))

    @router.get('')
    async def status(request: Request) -> dict:
        this_computer(request, 'speech')
        return service().status()

    @router.put('/settings')
    async def settings(body: SpeechSettings, request: Request) -> dict:
        this_computer(request, 'speech')
        speech = Speech(workspace_dir(), body.model_dump())
        try:
            for key in ('whisper_model', 'piper_model', 'piper_license'):
                if speech.settings[key]:
                    speech.settings[key] = speech.model(key).relative_to(speech.workspace).as_posix()
        except MediaError as exc:
            raise HTTPException(400, str(exc)) from exc
        get_state().store.set_setting('speech', speech.settings)
        return speech.status()

    async def execute(action, *args):
        if lock.locked():
            raise HTTPException(409, 'speech_busy')
        async with lock:
            try:
                return await asyncio.to_thread(action, *args)
            except (MediaError, OSError, UnicodeError) as exc:
                raise HTTPException(400, str(exc) if isinstance(exc, MediaError) else "speech_failed") from exc

    @router.post('/transcribe')
    async def transcribe(body: AudioIn, request: Request) -> dict:
        this_computer(request, 'speech')
        try:
            audio = base64.b64decode(body.audio, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(400, 'WAV') from exc
        return {'text': await execute(service().transcribe, audio)}

    @router.post('/speak')
    async def speak(body: TextIn, request: Request) -> Response:
        this_computer(request, 'speech')
        audio = await execute(service().synthesize, body.text)
        return Response(audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})

    return router
