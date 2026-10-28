"""Plain SRT/WebVTT editing and bounded local transcription/rendering with optional installed binaries.

No model download, shell, remote URL, in-place media overwrite or automatic execution. Each run uses a private
workspace copy; transcription temporaries are removed and the caller removes rendered output after download.
"""

from __future__ import annotations

import html
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, replace
from pathlib import Path

from spike.media import MediaError, Speech

MAX_TEXT = 1_000_000
MAX_FILE = 250_000_000
MAX_SECONDS = 600
FORMATS = {'.wav', '.mp3', '.m4a', '.aac', '.ogg', '.flac', '.mp4', '.mov', '.mkv', '.webm'}
VIDEO = {'.mp4', '.mov', '.mkv', '.webm'}
DEMUXERS = 'wav,mp3,mov,matroska,webm,ogg,flac,aac'


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


def validate(cues: list[Cue]) -> list[Cue]:
    if not 1 <= len(cues) <= 1000:
        raise MediaError('subtitles_invalid')
    previous = 0
    for cue in cues:
        if (type(cue.start_ms) is not int or type(cue.end_ms) is not int
                or not previous <= cue.start_ms < cue.end_ms <= 86_400_000
                or not cue.text.strip() or len(cue.text) > 2000 or '\n\n' in cue.text
                or any(ord(c) < 32 and c != '\n' for c in cue.text)):
            raise MediaError('subtitles_invalid')
        previous = cue.end_ms
    if sum(len(c.text) for c in cues) > MAX_TEXT:
        raise MediaError('subtitles_limit')
    return cues


def _time(raw: str) -> int:
    m = re.fullmatch(r'(?:(\d{2,}):)?([0-5]\d):([0-5]\d)[,.](\d{3})', raw)
    if not m:
        raise MediaError('subtitles_invalid')
    h, minute, sec, ms = m.groups()
    return ((int(h or 0) * 60 + int(minute)) * 60 + int(sec)) * 1000 + int(ms)


def parse(text: str, fmt: str) -> list[Cue]:
    if fmt not in {'srt', 'vtt'} or len(text) > MAX_TEXT:
        raise MediaError('subtitles_invalid')
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').strip()
    if fmt == 'vtt':
        lines = text.split('\n', 1)
        if lines[0] != 'WEBVTT':
            raise MediaError('subtitles_unsupported')
        text = lines[1].strip() if len(lines) > 1 else ''
    cues = []
    for block in re.split(r'\n[ \t]*\n', text):
        lines = block.splitlines()
        if fmt == 'vtt' and lines and (lines[0] == 'NOTE' or lines[0].startswith('NOTE ')):
            continue
        if lines and '-->' not in lines[0] and len(lines) > 1 and '-->' in lines[1]:
            lines = lines[1:]  # cue identifiers are not carried into the plain editor
        if len(lines) < 2 or lines[0].count(' --> ') != 1:
            raise MediaError('subtitles_invalid')
        start, end = lines[0].split(' --> ')
        body = '\n'.join(lines[1:])
        if '<' in body or '>' in body:  # styling/positioning is rejected, never silently lost
            raise MediaError('subtitles_unsupported')
        cues.append(Cue(_time(start), _time(end), html.unescape(body)))
    return validate(cues)


def _stamp(ms: int, fmt: str) -> str:
    seconds, milli = divmod(ms, 1000)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f'{hour:02d}:{minute:02d}:{second:02d}{"," if fmt == "srt" else "."}{milli:03d}'


def export_text(cues: list[Cue], fmt: str) -> str:
    validate(cues)
    if fmt not in {'srt', 'vtt'}:
        raise MediaError('subtitles_invalid')
    blocks = [f'{i}\n{_stamp(c.start_ms, fmt)} --> {_stamp(c.end_ms, fmt)}\n{html.escape(c.text, quote=False)}'
              for i, c in enumerate(cues, 1)]
    return ('WEBVTT\n\n' if fmt == 'vtt' else '') + '\n\n'.join(blocks) + '\n'


def edit(cues: list[Cue], action: str, *, index: int = 0, delta_ms: int = 0) -> list[Cue]:
    validate(cues)
    out = list(cues)
    if action == 'shift' and type(delta_ms) is int and abs(delta_ms) <= 86_400_000:
        out = [replace(c, start_ms=c.start_ms + delta_ms, end_ms=c.end_ms + delta_ms) for c in cues]
    elif action == 'split' and 0 <= index < len(cues):
        c = cues[index]
        words = c.text.split()
        if len(words) < 2 or c.end_ms - c.start_ms < 2:
            raise MediaError('subtitles_split')
        pivot, time = len(words) // 2, (c.start_ms + c.end_ms) // 2
        out[index:index + 1] = [Cue(c.start_ms, time, ' '.join(words[:pivot])),
                                Cue(time, c.end_ms, ' '.join(words[pivot:]))]
    elif action == 'merge' and 0 <= index < len(cues) - 1:
        a, b = cues[index:index + 2]
        out[index:index + 2] = [Cue(a.start_ms, b.end_ms, a.text + '\n' + b.text)]
    else:
        raise MediaError('subtitles_invalid')
    return validate(out)


class SubtitleStudio:
    def __init__(self, workspace: Path, model_workspace: Path, settings: dict):
        self.workspace, self.model_workspace, self.settings = workspace.resolve(), model_workspace, settings

    def source(self, relative: str) -> Path:
        p = Path(relative)
        if not relative or p.is_absolute() or ':' in relative or '\\' in relative or '..' in p.parts:
            raise MediaError('subtitles_path')
        target = self.workspace / p
        if (not target.resolve().is_relative_to(self.workspace) or any(
                (self.workspace / Path(*p.parts[:i])).is_symlink() for i in range(1, len(p.parts) + 1))):
            raise MediaError('subtitles_path')
        if not target.is_file() or target.suffix.lower() not in FORMATS:
            raise MediaError('subtitles_source')
        if not 0 < target.stat().st_size <= MAX_FILE:
            raise MediaError('subtitles_limit')
        return target

    @staticmethod
    def available() -> dict:
        return {key: bool(shutil.which(binary)) for key, binary in
                [('whisper', 'whisper-cli'), ('ffmpeg', 'ffmpeg'), ('ffprobe', 'ffprobe')]}

    @staticmethod
    def binary(name: str) -> str:
        path = shutil.which(name)
        if not path:
            raise MediaError({'whisper-cli': 'subtitles_whisper', 'ffmpeg': 'subtitles_ffmpeg',
                              'ffprobe': 'subtitles_ffprobe'}[name])
        return path

    @staticmethod
    def run(args: list[str], cwd: Path, *, capture: bool = False) -> str:
        try:
            result = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8', timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise MediaError('subtitles_command') from exc
        if result.returncode:
            raise MediaError('subtitles_command')
        return result.stdout or ''

    def probe(self, source: Path) -> dict:
        raw = self.run([self.binary('ffprobe'), '-v', 'error', '-protocol_whitelist', 'file,pipe',
                        '-format_whitelist', DEMUXERS, '-show_entries', 'format=duration:stream=codec_type,width,height',
                        '-of', 'json', str(source)], source.parent, capture=True)
        try:
            data = json.loads(raw)
            duration = float(data['format']['duration'])
            streams = data['streams']
            if (not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS
                    or not isinstance(streams, list) or len(streams) > 32
                    or any(s.get('width', 0) * s.get('height', 0) > 4096 * 2160
                           or max(s.get('width', 0), s.get('height', 0)) > 4096 for s in streams)):
                raise ValueError()
            return {'duration': duration, 'video': any(s.get('codec_type') == 'video' for s in streams)}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise MediaError('subtitles_limit') from exc

    def copy(self, source: Path, folder: Path) -> Path:
        target = folder / ('source' + source.suffix.lower())
        with source.open('rb') as src, target.open('xb') as dst:
            remaining = MAX_FILE
            while chunk := src.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise MediaError('subtitles_limit')
                dst.write(chunk)
        return target

    def transcribe(self, relative: str) -> list[Cue]:
        if not self.settings.get('enabled'):
            raise MediaError('disabled')
        source, binary = self.source(relative), self.binary('whisper-cli')
        model = Speech(self.model_workspace, self.settings).model('whisper_model')
        with tempfile.TemporaryDirectory(prefix='subtitles-', dir=self.workspace) as directory:
            folder = Path(directory)
            source = self.copy(source, folder)
            direct = False
            if source.suffix == '.wav':
                try:
                    with wave.open(str(source), 'rb') as wav:
                        direct = wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000
                except (wave.Error, EOFError):
                    pass
            if direct:
                audio = source
            else:
                self.probe(source)
                audio = folder / 'audio.wav'
                self.run([self.binary('ffmpeg'), '-nostdin', '-v', 'error', '-n', '-threads', '2',
                          '-protocol_whitelist', 'file,pipe', '-format_whitelist', DEMUXERS, '-i', str(source),
                          '-t', str(MAX_SECONDS + 1), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                          str(audio)], folder)
            try:
                with wave.open(str(audio), 'rb') as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000
                            or not 0 < duration <= MAX_SECONDS):
                        raise MediaError('subtitles_wav')
            except (wave.Error, EOFError, ZeroDivisionError) as exc:
                raise MediaError('subtitles_wav') from exc
            output = folder / 'captions'
            self.run([binary, '-m', str(model), '-f', str(audio), '-l', 'auto', '-t', '2', '-ng',
                      '-osrt', '-of', str(output)], folder)
            srt = output.with_suffix('.srt')
            if not srt.is_file() or srt.stat().st_size > MAX_TEXT:
                raise MediaError('subtitles_invalid')
            cues = parse(srt.read_text(encoding='utf-8'), 'srt')
            if cues[-1].end_ms > round(duration * 1000) + 1000:
                raise MediaError('subtitles_invalid')
            return cues

    def burn(self, relative: str, cues: list[Cue]) -> Path:
        validate(cues)
        source, binary = self.source(relative), self.binary('ffmpeg')
        if source.suffix.lower() not in VIDEO:
            raise MediaError('subtitles_video')
        folder = Path(tempfile.mkdtemp(prefix='subtitles-', dir=self.workspace))
        try:
            source = self.copy(source, folder)
            info = self.probe(source)
            if not info['video'] or cues[-1].end_ms > round(info['duration'] * 1000):
                raise MediaError('subtitles_video')
            (folder / 'captions.srt').write_text(export_text(cues, 'srt'), encoding='utf-8')
            output = folder / 'subtitled.mp4'
            self.run([binary, '-nostdin', '-v', 'error', '-n', '-threads', '2', '-filter_threads', '1',
                      '-protocol_whitelist', 'file,pipe', '-format_whitelist', DEMUXERS, '-i', str(source),
                      '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'subtitles=captions.srt', '-c:v', 'libx264',
                      '-threads', '2', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                      '-map_metadata', '-1', '-movflags', '+faststart', '-fs', str(MAX_FILE), str(output)], folder)
            if not output.is_file() or not 0 < output.stat().st_size < MAX_FILE:
                raise MediaError('subtitles_command')
            rendered = self.probe(output)
            if not rendered['video'] or abs(rendered['duration'] - info['duration']) > 0.25:
                raise MediaError('subtitles_command')
            return output
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
