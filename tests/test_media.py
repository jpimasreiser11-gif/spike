"""A13: local speech commands and vision payloads, without network or real weights."""

import base64
import io
import json
import sys
import wave

import httpx
import pytest

from spike.core.types import ChatRequest, Message
from spike.media import MediaError, Speech, validate_images
from spike.providers.anthropic import AnthropicProvider
from spike.providers.base import ProviderConfig
from spike.providers.openai_compat import OpenAICompatProvider

IMAGE = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode()


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 160)
    return out.getvalue()


def fake(tmp_path, monkeypatch, name, source):
    """Run a fake executable through Python on every platform, including Windows."""
    script = tmp_path / (name + '.py')
    script.write_text(source, encoding='utf-8')
    monkeypatch.setattr('spike.media.shutil.which', lambda binary: str(script) if binary == name else None)
    real_run = __import__('subprocess').run

    def run(args, **kwargs):
        return real_run([sys.executable, *args], **kwargs)

    monkeypatch.setattr('spike.media.subprocess.run', run)


def speech(tmp_path):
    (tmp_path / 'model.bin').write_bytes(b'fake')
    (tmp_path / 'voice.onnx').write_bytes(b'fake')
    (tmp_path / 'LICENSE.txt').write_text('CC0-1.0 voice fixture', encoding='utf-8')
    return Speech(tmp_path, {'enabled': True, 'whisper_model': 'model.bin', 'piper_model': 'voice.onnx',
                             'piper_license': 'LICENSE.txt'})


def test_fake_whisper(tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, 'whisper-cli', '''import pathlib, sys
args = sys.argv
assert pathlib.Path(args[args.index('-m') + 1]).name == 'model.bin'
assert args[args.index('-l') + 1] == 'auto'
pathlib.Path(args[args.index('-of') + 1] + '.txt').write_text('Hola mundo', encoding='utf-8')
''')
    service = speech(tmp_path)
    assert service.transcribe(wav()) == 'Hola mundo'
    assert not list(tmp_path.glob('speech-*'))


def test_fake_piper_and_license(tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, 'piper', '''import pathlib, sys, wave
assert sys.stdin.read() == 'Hola'
with wave.open(sys.argv[sys.argv.index('--output_file') + 1], 'wb') as out:
    out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\\0\\0' * 10)
''')
    service = speech(tmp_path)
    assert service.status()['license'] == 'CC0-1.0 voice fixture'
    assert service.synthesize('Hola').startswith(b'RIFF')
    assert not list(tmp_path.glob('speech-*'))


def test_speech_refuses_missing_disabled_outside_and_bad_audio(tmp_path, monkeypatch):
    service = speech(tmp_path)
    monkeypatch.setattr('spike.media.shutil.which', lambda name: None)
    with pytest.raises(MediaError, match='missing'):
        service.transcribe(wav())
    service.settings['enabled'] = False
    with pytest.raises(MediaError, match='disabled'):
        service.synthesize('hello')
    service.settings['enabled'] = True
    service.settings['whisper_model'] = '../outside'
    with pytest.raises(MediaError, match='workspace'):
        service.model('whisper_model')
    with pytest.raises(MediaError, match='WAV'):
        service.transcribe(b'not wav')


@pytest.mark.parametrize('provider_type', [OpenAICompatProvider, AnthropicProvider])
async def test_vision_content_parts_fake_provider(provider_type):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b'data: [DONE]\n\n')

    cfg = ProviderConfig(id='fake', kind='openai', name='fake', base_url='http://fake',
                         capabilities={'vision': True})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = provider_type(cfg, client=client)
        _ = [e async for e in provider.stream(ChatRequest(messages=[Message(role='user', content='Describe',
                                                                          images=[IMAGE])]))]
    parts = seen[0]['messages'][0]['content']
    assert parts[0] == {'type': 'text', 'text': 'Describe'}
    if provider_type is OpenAICompatProvider:
        assert parts[1] == {'type': 'image_url', 'image_url': {'url': IMAGE}}
    else:
        assert parts[1]['source']['data'] == IMAGE.split(',')[1]
        assert parts[1]['source']['media_type'] == 'image/png'


async def test_text_only_provider_refuses_images_without_transport():
    provider = OpenAICompatProvider(ProviderConfig(id='local', kind='openai', name='local', local=True,
                                                  base_url='http://never'))
    events = [e async for e in provider.stream(ChatRequest(messages=[Message(role='user', images=[IMAGE])]))]
    assert events[0].kind == 'error' and 'vision' in events[0].text


def test_image_validation():
    assert validate_images([IMAGE]) == [IMAGE]
    for images in [['https://remote/image.png'], ['data:image/svg+xml;base64,PHN2Zz4='], [IMAGE] * 5,
                   ['data:image/png;base64,???']]:
        with pytest.raises(MediaError):
            validate_images(images)


def test_speech_timeout_and_failure_cleanup(tmp_path, monkeypatch):
    import subprocess

    service = speech(tmp_path)
    monkeypatch.setattr('spike.media.shutil.which', lambda name: sys.executable)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('fake', 90)

    monkeypatch.setattr('spike.media.subprocess.run', timeout)
    with pytest.raises(MediaError, match='speech_failed'):
        service.transcribe(wav())
    assert not list(tmp_path.glob('speech-*'))


async def test_local_llamacpp_refuses_before_adapters_request():
    from spike.providers.llamacpp import LlamaCppProvider

    def handler(request):
        raise AssertionError('must not contact local model')

    cfg = ProviderConfig(id='local', kind='llamacpp', name='local', base_url='http://never', local=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LlamaCppProvider(cfg, client=client)
        events = [e async for e in provider.stream(ChatRequest(messages=[Message(role='user', images=[IMAGE])]))]
    assert events[0].text == 'vision_required'


def test_piper_requires_license_and_reports_failed_program(tmp_path, monkeypatch):
    service = speech(tmp_path)
    service.settings['piper_license'] = ''
    monkeypatch.setattr('spike.media.shutil.which', lambda name: sys.executable)
    with pytest.raises(MediaError, match='license_missing'):
        service.synthesize('hello')
    service.settings['piper_license'] = 'LICENSE.txt'
    fake(tmp_path, monkeypatch, 'piper', 'import sys; sys.exit(2)')
    with pytest.raises(MediaError, match='speech_failed'):
        service.synthesize('hello')
    assert not list(tmp_path.glob('speech-*'))


def test_symlink_outside_workspace_refused(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    (tmp_path / 'model').write_bytes(b'fake')
    try:
        (root / 'link').symlink_to(tmp_path / 'model')
    except OSError:
        pytest.skip('symlinks unavailable')
    service = Speech(root, {'whisper_model': 'link'})
    with pytest.raises(MediaError, match='workspace'):
        service.model('whisper_model')


@pytest.mark.parametrize('binary', ['whisper-cli', 'piper'])
def test_malformed_speech_output_is_a_clear_error(tmp_path, monkeypatch, binary):
    service = speech(tmp_path)
    if binary == 'whisper-cli':
        source = "import pathlib, sys; pathlib.Path(sys.argv[sys.argv.index('-of')+1]+'.txt').write_bytes(b'\\xff')"
    else:
        source = "import pathlib, sys; pathlib.Path(sys.argv[sys.argv.index('--output_file')+1]).write_bytes(b'bad')"
    fake(tmp_path, monkeypatch, binary, source)
    with pytest.raises(MediaError, match='speech_failed'):
        service.transcribe(wav()) if binary == 'whisper-cli' else service.synthesize('hello')
    assert not list(tmp_path.glob('speech-*'))
