"""A14: plain timed text, safe edits and optional local programs; no downloads or weights."""

import subprocess
import sys

import pytest

from spike.media import MediaError
from spike.subtitles import Cue, SubtitleStudio, edit, export_text, parse, validate
from tests.test_media import wav

CUES = [Cue(0, 1000, 'Hola & adiós'), Cue(1200, 2000, 'Segunda línea\ncon detalle')]


@pytest.mark.parametrize('fmt', ['srt', 'vtt'])
def test_round_trip_and_unicode(fmt):
    assert parse('\ufeff' + export_text(CUES, fmt).replace('\n', '\r\n'), fmt) == CUES
    assert export_text(CUES, fmt).endswith('\n')


def test_shift_split_merge_are_non_mutating():
    moved = edit(CUES, 'shift', delta_ms=250)
    assert moved[0].start_ms == 250 and CUES[0].start_ms == 0
    divided = edit(CUES, 'split', index=1)
    assert len(divided) == 3 and divided[1].end_ms == divided[2].start_ms == 1600
    merged = edit(divided, 'merge', index=1)
    assert merged[1].start_ms == 1200 and merged[1].end_ms == 2000
    assert 'Segunda' in merged[1].text and 'detalle' in merged[1].text
    with pytest.raises(MediaError):
        edit(CUES, 'shift', delta_ms=-1)
    with pytest.raises(MediaError):
        edit(CUES, 'merge', index=1)
    with pytest.raises(MediaError):
        edit([Cue(0, 1, 'x')], 'split')


@pytest.mark.parametrize('raw,fmt', [
    ('1\n00:00:02,000 --> 00:00:01,000\nx', 'srt'),
    ('WEBVTT\n\n00:00.000 --> 00:01.000 position:20%\nx', 'vtt'),
    ('WEBVTT\n\nSTYLE\n::cue { color: red; }', 'vtt'),
    ('1\n00:00:00,000 --> 00:00:01,000\n<b>x</b>', 'srt'),
    ('WEBVTT\n\n00:61.000 --> 00:62.000\nx', 'vtt'),
])
def test_malformed_and_unsupported_import_is_rejected(raw, fmt):
    with pytest.raises(MediaError):
        parse(raw, fmt)


def test_limits_and_overlaps():
    for cues in [[Cue(1, 1, 'x')], [Cue(0, 1000, 'x'), Cue(500, 2000, 'y')], [Cue(0, 2, '')],
                 [Cue(0, 2, 'x' * 2001)]]:
        with pytest.raises(MediaError):
            validate(cues)


@pytest.fixture
def studio(tmp_path):
    (tmp_path / 'model.bin').write_bytes(b'fake weights')
    (tmp_path / 'clip.wav').write_bytes(wav())
    return SubtitleStudio(tmp_path, tmp_path, {'enabled': True, 'whisper_model': 'model.bin'})


def fake_programs(tmp_path, monkeypatch, broken=False):
    """Use the interpreter, not a POSIX shebang, so subprocess assertions also run on Windows."""
    sources = {
        'whisper-cli': """import pathlib, sys
assert '-osrt' in sys.argv and '-ng' in sys.argv
pathlib.Path(sys.argv[sys.argv.index('-of')+1]+'.srt').write_text('1\\n00:00:00,000 --> 00:00:00,010\\nHola\\n', encoding='utf-8')
""",
        'ffprobe': """import json
print(json.dumps({'format':{'duration':'1'},'streams':[{'codec_type':'video','width':640,'height':360}]}))
""",
        'ffmpeg': """import pathlib, sys, wave
assert '-protocol_whitelist' in sys.argv and '-nostdin' in sys.argv
if sys.argv[-1].endswith('.wav'):
    with wave.open(sys.argv[-1], 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(b'\\0\\0'*160)
else:
    assert 'subtitles=captions.srt' in sys.argv
    assert pathlib.Path('captions.srt').is_file()
    pathlib.Path(sys.argv[-1]).write_bytes(b'\\0\\0\\0\\x18ftypmp42fake')
""",
    }
    paths = {}
    for name, source in sources.items():
        p = tmp_path / (name + '.py')
        p.write_text('raise SystemExit(1)' if broken else source, encoding='utf-8')
        paths[name] = str(p)
    monkeypatch.setattr('spike.subtitles.shutil.which', paths.get)
    original = subprocess.run
    def run(args, **kwargs):
        return original([sys.executable, *args], **kwargs)
    monkeypatch.setattr('spike.subtitles.subprocess.run', run)


def test_transcribes_tiny_wav_with_fake_whisper(studio, tmp_path, monkeypatch):
    fake_programs(tmp_path, monkeypatch)
    cues = studio.transcribe('clip.wav')
    assert cues == [Cue(0, 10, 'Hola')]
    assert not list(tmp_path.glob('subtitles-*'))


def test_converts_video_and_burns_copy(studio, tmp_path, monkeypatch):
    fake_programs(tmp_path, monkeypatch)
    source = tmp_path / 'clip.mp4'
    source.write_bytes(b'fake video')
    assert studio.transcribe('clip.mp4')[0].text == 'Hola'
    output = studio.burn('clip.mp4', [Cue(0, 500, 'Título')])
    assert output.read_bytes()[4:8] == b'ftyp'
    assert source.read_bytes() == b'fake video'
    assert output.parent.parent == tmp_path
    __import__('shutil').rmtree(output.parent)


def test_missing_disabled_paths_and_failed_command(studio, tmp_path, monkeypatch):
    monkeypatch.setattr('spike.subtitles.shutil.which', lambda _: None)
    with pytest.raises(MediaError, match='subtitles_whisper'):
        studio.transcribe('clip.wav')
    studio.settings['enabled'] = False
    with pytest.raises(MediaError, match='disabled'):
        studio.transcribe('clip.wav')
    studio.settings['enabled'] = True
    for path in ['../secret.wav', str(tmp_path / 'clip.wav'), 'https://example.com/a.wav']:
        with pytest.raises(MediaError):
            studio.source(path)
    fake_programs(tmp_path, monkeypatch, broken=True)
    with pytest.raises(MediaError, match='subtitles_command'):
        studio.transcribe('clip.wav')
    assert not list(tmp_path.glob('subtitles-*'))


def test_external_symlink_and_timeout_leave_no_temporary_files(studio, tmp_path, monkeypatch):
    from pathlib import Path
    link = tmp_path / 'alias.wav'
    try:
        link.symlink_to(tmp_path / 'clip.wav')
    except OSError:
        pytest.skip('symlink creation unavailable')
    with pytest.raises(MediaError, match='subtitles_path'):
        studio.source('alias.wav')
    monkeypatch.setattr('spike.subtitles.shutil.which', lambda name: name)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('fake', 300)
    monkeypatch.setattr('spike.subtitles.subprocess.run', timeout)
    with pytest.raises(MediaError, match='subtitles_command'):
        studio.transcribe('clip.wav')
    assert not list(Path(tmp_path).glob('subtitles-*'))


def test_probe_rejects_missing_nonfinite_and_long_duration(studio, monkeypatch):
    import json
    monkeypatch.setattr(studio, 'binary', lambda _: 'fake')
    for raw in ['{}', '{bad', json.dumps({'format': {'duration': 'nan'}, 'streams': []}),
                json.dumps({'format': {'duration': '601'}, 'streams': []}),
                json.dumps({'format': {'duration': '1'}, 'streams': [{'width': 100000, 'height': 10000}]})]:
        monkeypatch.setattr(studio, 'run', lambda *a, value=raw, **k: value)
        with pytest.raises(MediaError, match='subtitles_limit'):
            studio.probe(studio.workspace / 'clip.wav')


def test_stereo_wav_is_converted_when_ffmpeg_is_available(studio, tmp_path, monkeypatch):
    import wave
    fake_programs(tmp_path, monkeypatch)
    with wave.open(str(tmp_path / 'stereo.wav'), 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b'\0\0' * 480)
    assert studio.transcribe('stereo.wav')[0].text == 'Hola'


@pytest.mark.parametrize('binary,code', [('ffmpeg', 'subtitles_ffmpeg'), ('ffprobe', 'subtitles_ffprobe'),
                                        ('whisper-cli', 'subtitles_whisper')])
def test_optional_programs_have_actionable_errors(monkeypatch, binary, code):
    monkeypatch.setattr('spike.subtitles.shutil.which', lambda _: None)
    with pytest.raises(MediaError, match=code):
        SubtitleStudio.binary(binary)


def test_burn_rejects_truncated_output_and_cleans(studio, tmp_path, monkeypatch):
    fake_programs(tmp_path, monkeypatch)
    (tmp_path / 'clip.mp4').write_bytes(b'fake')
    monkeypatch.setattr(studio, 'probe', lambda path: {'video': True, 'duration': 1 if path.name != 'subtitled.mp4' else .2})
    with pytest.raises(MediaError, match='subtitles_command'):
        studio.burn('clip.mp4', [Cue(0, 500, 'Hola')])
    assert not list(tmp_path.glob('subtitles-*'))
