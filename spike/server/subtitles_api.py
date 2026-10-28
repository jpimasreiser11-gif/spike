"""A14 local subtitle workbench: plain text edits, explicit transcription and copied video downloads."""

import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from spike.media import DEFAULTS, MediaError
from spike.runtime.paths import workspace_dir
from spike.server.speech_jobs import execute_speech
from spike.subtitles import MAX_SECONDS, MAX_TEXT, Cue, SubtitleStudio, edit, export_text, parse


class CueIn(BaseModel):
    start_ms: int = Field(ge=0, le=86_400_000, strict=True)
    end_ms: int = Field(ge=1, le=86_400_000, strict=True)
    text: str = Field(min_length=1, max_length=2000)


class CuesIn(BaseModel):
    cues: list[CueIn] = Field(min_length=1, max_length=1000)

    def values(self) -> list[Cue]:
        return [Cue(**cue.model_dump()) for cue in self.cues]


class ImportIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    format: Literal['srt', 'vtt']


class ExportIn(CuesIn):
    format: Literal['srt', 'vtt']


class EditIn(CuesIn):
    action: Literal['shift', 'split', 'merge']
    index: int = Field(default=0, ge=0, le=999)
    delta_ms: int = Field(default=0, ge=-86_400_000, le=86_400_000, strict=True)


class SourceIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    project_id: str | None = Field(default=None, max_length=128)
    approved: bool = False


class BurnIn(SourceIn, CuesIn):
    pass


def remove_render(path: Path) -> None:
    shutil.rmtree(path.parent, ignore_errors=True)


class RenderResponse(FileResponse):
    """Release private render files even when the download is interrupted after headers were sent."""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            remove_render(Path(self.path))


def create_subtitles_router(get_state: Callable[[], Any], this_computer: Callable[[Request, str], None]) -> APIRouter:
    router = APIRouter(prefix='/api/subtitles')

    def studio(project_id: str | None = None) -> SubtitleStudio:
        state = get_state()
        if project_id and state.store.get_project(project_id) is None:
            raise HTTPException(404, 'project not found')
        root = state.project_files.folder(project_id) if project_id else workspace_dir()
        return SubtitleStudio(root, workspace_dir(), state.store.get_setting('speech', dict(DEFAULTS)))

    def safe(action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except MediaError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('')
    def status(request: Request):
        this_computer(request, 'subtitles')
        return {'enabled': bool(studio().settings.get('enabled')), 'max_seconds': MAX_SECONDS,
                **SubtitleStudio.available()}

    @router.post('/import')
    def read(body: ImportIn, request: Request):
        this_computer(request, 'subtitles')
        return {'cues': [asdict(c) for c in safe(parse, body.text, body.format)]}

    @router.post('/edit')
    def transform(body: EditIn, request: Request):
        this_computer(request, 'subtitles')
        cues = safe(edit, body.values(), body.action, index=body.index, delta_ms=body.delta_ms)
        return {'cues': [asdict(c) for c in cues]}

    @router.post('/export')
    def download(body: ExportIn, request: Request):
        this_computer(request, 'subtitles')
        content = safe(export_text, body.values(), body.format)
        return Response(content, media_type='text/vtt' if body.format == 'vtt' else 'application/x-subrip',
                        headers={'Cache-Control': 'no-store',
                                 'Content-Disposition': f'attachment; filename="subtitles.{body.format}"'})

    @router.post('/transcribe')
    async def transcribe(body: SourceIn, request: Request):
        this_computer(request, 'subtitles')
        if not body.approved:
            raise HTTPException(403, 'subtitles_approval')
        cues = await execute_speech(get_state(), studio(body.project_id).transcribe, body.path)
        return {'cues': [asdict(c) for c in cues]}

    @router.post('/burn')
    async def burn(body: BurnIn, request: Request):
        this_computer(request, 'subtitles')
        if not body.approved:
            raise HTTPException(403, 'subtitles_approval')
        target = await execute_speech(get_state(), studio(body.project_id).burn, body.path, body.values(),
                                      cleanup=remove_render)
        return RenderResponse(target, media_type='video/mp4', filename='subtitled.mp4',
                              headers={'Cache-Control': 'no-store'})

    return router
