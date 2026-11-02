"""Explicit local actions, shared speech exclusion, editing and downloads."""

import asyncio
import contextlib
from dataclasses import asdict

from fastapi.testclient import TestClient

from spike.server.app import create_app
from tests.test_media import wav
from tests.test_server import env as env
from tests.test_subtitles import CUES, fake_programs


def local(env):
    _, state, scripts = env
    return TestClient(create_app(state), client=('127.0.0.1', 50000)), state, scripts


def test_open_import_edit_export_never_runs_a_program(env, monkeypatch):
    client, _, scripts = local(env)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected program')))
    status = client.get('/api/subtitles')
    assert status.status_code == 200 and status.json()['max_seconds'] == 600
    raw = '1\n00:00:00,000 --> 00:00:01,000\nHola mundo\n'
    parsed = client.post('/api/subtitles/import', json={'text': raw, 'format': 'srt'})
    cues = parsed.json()['cues']
    edited = client.post('/api/subtitles/edit', json={'cues': cues, 'action': 'shift', 'delta_ms': 500})
    assert edited.json()['cues'][0]['start_ms'] == 500
    out = client.post('/api/subtitles/export', json={'cues': edited.json()['cues'], 'format': 'vtt'})
    assert out.text.startswith('WEBVTT') and '00:00:00.500' in out.text
    assert out.headers['cache-control'] == 'no-store'
    assert 'attachment' in out.headers['content-disposition']
    assert not any(p.requests for p in scripts.values())


def test_transcription_needs_approval_setting_and_local_origin(env, tmp_path, monkeypatch):
    client, state, _ = local(env)
    ws = tmp_path / 'ws'
    ws.mkdir(exist_ok=True)
    (ws / 'clip.wav').write_bytes(wav())
    (ws / 'model.bin').write_bytes(b'fake')
    fake_programs(tmp_path, monkeypatch)
    body = {'path': 'clip.wav'}
    assert client.post('/api/subtitles/transcribe', json=body).status_code == 403
    body['approved'] = True
    assert client.post('/api/subtitles/transcribe', json=body).status_code == 400
    state.store.set_setting('speech', {'enabled': True, 'whisper_model': 'model.bin'})
    assert client.post('/api/subtitles/transcribe', json=body).json()['cues'][0]['text'] == 'Hola'
    assert client.post('/api/subtitles/transcribe', json=body,
                       headers={'origin': 'https://elsewhere.test'}).status_code == 403
    other = TestClient(create_app(state), client=('192.0.2.1', 50000))
    assert other.post('/api/subtitles/transcribe', json=body).status_code == 403
    assert client.post('/api/subtitles/transcribe', json={**body, 'project_id': 'missing'}).status_code == 404


def test_render_copies_and_cleans_download(env, tmp_path, monkeypatch):
    client, state, _ = local(env)
    p = state.store.create_project('Film')
    folder = state.project_files.folder(p['id'])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'clip.mp4').write_bytes(b'original')
    fake_programs(tmp_path, monkeypatch)
    body = {'path': 'clip.mp4', 'project_id': p['id'], 'cues': [asdict(CUES[0])]}
    assert client.post('/api/subtitles/burn', json=body).status_code == 403
    result = client.post('/api/subtitles/burn', json={**body, 'approved': True})
    assert result.status_code == 200, result.text
    assert result.content[4:8] == b'ftyp'
    assert (folder / 'clip.mp4').read_bytes() == b'original'
    assert not list(folder.glob('subtitles-*'))


def test_speech_and_subtitles_share_one_gate(env, tmp_path, monkeypatch):
    client, state, _ = local(env)
    state.speech_lock = asyncio.Lock()
    asyncio.run(state.speech_lock.acquire())
    for endpoint, body in [('/api/subtitles/transcribe', {'path': 'clip.wav', 'approved': True}),
                           ('/api/media/speak', {'text': 'hello'})]:
        response = client.post(endpoint, json=body)
        assert response.status_code == 409
    state.speech_lock.release()


def test_disconnected_speech_retains_gate_until_thread_stops(env):
    import threading

    from fastapi import HTTPException

    from spike.server.speech_jobs import execute_speech
    _, state, _ = env
    started, release = threading.Event(), threading.Event()
    cleaned = []
    def blocking():
        started.set()
        release.wait(3)
        return 'render'
    async def check():
        task = asyncio.create_task(execute_speech(state, blocking, cleanup=cleaned.append))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert state.speech_lock.locked()
        try:
            await execute_speech(state, lambda: None)
            raise AssertionError('second job entered')
        except HTTPException as exc:
            assert exc.status_code == 409
        finally:
            release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert not state.speech_lock.locked()
        assert cleaned == ['render']
    asyncio.run(check())


def test_interrupted_download_removes_private_render_folder(tmp_path):
    from spike.server.subtitles_api import RenderResponse
    folder = tmp_path / 'render'
    folder.mkdir()
    target = folder / 'subtitled.mp4'
    target.write_bytes(b'fixture')
    async def check():
        async def receive():
            return {'type': 'http.disconnect'}
        async def send(message):
            raise OSError('disconnected after response headers')
        with contextlib.suppress(OSError):
            await RenderResponse(target)({'type': 'http', 'method': 'GET', 'headers': []}, receive, send)
        assert not folder.exists()
    asyncio.run(check())
