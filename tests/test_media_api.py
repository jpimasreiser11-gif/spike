"""Media routes and composer images use the existing guarded chat path."""

import base64

from tests.helpers import text
from tests.test_media import IMAGE, fake, wav
from tests.test_server import env as env
from tests.test_server import events_of


def test_images_reach_chat_provider_and_history(env):
    client, state, scripts = env
    client.get('/api/providers')
    client.patch('/api/providers/spike-local', json={'capabilities': {'vision': True}})
    scripts['spike-local']._script = [text('image answer'), text('follow up')]
    response = client.post('/api/chat', json={'message': 'Describe', 'images': [IMAGE]})
    assert response.status_code == 200, response.text
    assert scripts['spike-local'].requests[-1].messages[-1].images == [IMAGE]
    cid = events_of(response)[0]['id']
    response = client.post('/api/chat', json={'message': 'Again', 'conversation_id': cid})
    assert response.status_code == 200
    assert any(m.images == [IMAGE] for m in scripts['spike-local'].requests[-1].messages)


def test_images_refused_before_saving_or_running(env):
    client, state, scripts = env
    response = client.post('/api/chat', json={'message': 'Describe', 'images': [IMAGE]})
    assert response.status_code == 400 and response.json()['detail'] == 'vision_required'
    assert not state.store.list_conversations()
    assert client.post('/api/chat', json={'message': 'x', 'images': ['https://remote']}).status_code == 400


def test_voice_routes_explicit_setting_and_local_only(env, tmp_path, monkeypatch):
    client, state, _ = env
    from fastapi.testclient import TestClient

    from spike.server.app import create_app

    client = TestClient(create_app(state), client=("127.0.0.1", 50000))
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    (workspace / 'model.bin').write_bytes(b'fake')
    fake(tmp_path, monkeypatch, 'whisper-cli', '''import pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('-of') + 1] + '.txt').write_text('Dictado', encoding='utf-8')
''')
    assert client.get('/api/media').json()['enabled'] is False
    body = {'audio': base64.b64encode(wav()).decode()}
    assert client.post('/api/media/transcribe', json=body).status_code == 400
    response = client.put('/api/media/settings', json={'enabled': True, 'whisper_model': 'model.bin'})
    assert response.status_code == 200
    assert client.post('/api/media/transcribe', json=body).json() == {'text': 'Dictado'}
    assert client.put('/api/media/settings', json={'whisper_model': '../bad'}).status_code == 400
    assert client.post('/api/media/transcribe', json={'audio': '???'}).status_code == 400
    assert client.post('/api/media/transcribe', json=body, headers={'origin': 'https://evil.test'}).status_code == 403


def test_image_answer_is_private_and_remote_permission_is_required(env):
    client, state, scripts = env
    client.patch('/api/providers/spike-local', json={'capabilities': {'vision': True}})
    client.get('/api/providers')
    scripts['spike-local']._script = [text('Private image summary')]
    response = client.post('/api/chat', json={'message': 'Describe', 'images': [IMAGE]})
    cid = events_of(response)[0]['id']
    assert state.store.messages(cid)[-1]['meta']['private'] is True
    client.post('/api/providers', json={'preset': 'openai', 'model': 'fake', 'allow_paid': True,
                                        'capabilities': {'vision': True}})
    response = client.post('/api/chat', json={'message': 'Describe', 'provider_id': 'openai', 'images': [IMAGE]})
    assert response.status_code == 400 and response.json()['detail'] == 'images_private'
    assert not scripts.get('openai') or not scripts['openai'].requests


def test_synthesis_route_returns_wav_after_explicit_enable(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from spike.server.app import create_app

    _, state, _ = env
    client = TestClient(create_app(state), client=('127.0.0.1', 50000))
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    (workspace / 'voice.onnx').write_bytes(b'fake')
    (workspace / 'LICENSE.txt').write_text('CC0-1.0 voice fixture', encoding='utf-8')
    fake(tmp_path, monkeypatch, 'piper', '''import sys, wave
assert sys.stdin.read() == 'Hola'
with wave.open(sys.argv[sys.argv.index('--output_file') + 1], 'wb') as out:
    out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\\0\\0' * 10)
''')
    status = client.put('/api/media/settings', json={'enabled': True, 'piper_model': 'voice.onnx',
                                                    'piper_license': 'LICENSE.txt'}).json()
    assert status['license'] == 'CC0-1.0 voice fixture'
    response = client.post('/api/media/speak', json={'text': 'Hola'})
    assert response.status_code == 200 and response.headers['content-type'] == 'audio/wav'
    assert response.headers['cache-control'] == 'no-store' and response.content.startswith(b'RIFF')
    assert not list(workspace.glob('speech-*'))
