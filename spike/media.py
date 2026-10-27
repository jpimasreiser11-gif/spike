"""Bounded image inputs and opt-in speech via installed command line programs.

Models and license files are selected inside the workspace. Commands receive no shell, run with a timeout, and
write only to a temporary workspace directory which is removed on success and failure. No downloads or telemetry.
"""

from __future__ import annotations

import base64
import binascii
import io
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

DEFAULTS = {'enabled': False, 'whisper_model': '', 'piper_model': '', 'piper_license': ''}
MAX_AUDIO = 8_000_000


class MediaError(ValueError):
    """A safe error code; the browser supplies the translated explanation."""


def validate_images(images: list[str]) -> list[str]:
    if len(images) > 4:
        raise MediaError('images_limit')
    for image in images:
        if len(image) > 2_800_000:
            raise MediaError('images_limit')
        header, sep, data = image.partition(',')
        if not sep or header not in {'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'}:
            raise MediaError('image_invalid')
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise MediaError('image_invalid') from exc
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') if 'png' in header else
                raw.startswith(b'\xff\xd8\xff') if 'jpeg' in header else
                raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'):
            raise MediaError('image_invalid')
    return images


class Speech:
    def __init__(self, workspace: Path, settings: dict):
        self.workspace, self.settings = workspace.resolve(), settings

    def model(self, key: str) -> Path:
        value = self.settings.get(key, '')
        path = (self.workspace / value).resolve()
        if not path.is_relative_to(self.workspace):
            raise MediaError('workspace')
        if not value or not path.is_file():
            raise MediaError('model_missing')
        return path

    def status(self) -> dict:
        license_text = ''
        try:
            path = self.model('piper_license')
            if path.stat().st_size <= 32_000:
                license_text = path.read_text(encoding='utf-8')
        except (MediaError, OSError, UnicodeError):
            pass
        return {**self.settings, 'whisper': bool(shutil.which('whisper-cli')), 'piper': bool(shutil.which('piper')),
                'license': license_text}

    def command(self, binary: str) -> str:
        if not self.settings.get('enabled'):
            raise MediaError('disabled')
        executable = shutil.which(binary)
        if not executable:
            raise MediaError('binary_missing')
        return executable

    def run(self, args: list[str], *, text: str | None = None) -> None:
        try:
            result = subprocess.run(args, input=text, text=True, encoding='utf-8', capture_output=True,
                                    timeout=90, cwd=self.workspace, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MediaError('speech_failed') from exc
        if result.returncode:
            raise MediaError('speech_failed')  # never expose command output or paths

    def transcribe(self, audio: bytes) -> str:
        if len(audio) > MAX_AUDIO:
            raise MediaError('audio_limit')
        try:
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
                    raise MediaError('WAV')
                if wav.getnframes() > 16000 * 120:
                    raise MediaError('audio_limit')
        except (wave.Error, EOFError) as exc:
            raise MediaError('WAV') from exc
        executable, model = self.command('whisper-cli'), self.model('whisper_model')
        with tempfile.TemporaryDirectory(prefix='speech-', dir=self.workspace) as folder:
            source, output = Path(folder) / 'input.wav', Path(folder) / 'output'
            source.write_bytes(audio)
            self.run([executable, '-m', str(model), '-f', str(source), '-l', 'auto', '-otxt', '-of', str(output)])
            target = output.with_suffix('.txt')
            if not target.is_file() or target.stat().st_size > 100_000:
                raise MediaError('speech_failed')
            try:
                return target.read_text(encoding='utf-8').strip()
            except (OSError, UnicodeError) as exc:
                raise MediaError('speech_failed') from exc

    def synthesize(self, text: str) -> bytes:
        executable, model = self.command('piper'), self.model('piper_model')
        if not text.strip() or len(text) > 10_000:
            raise MediaError('text_limit')
        if not self.status()['license']:
            raise MediaError('license_missing')
        with tempfile.TemporaryDirectory(prefix='speech-', dir=self.workspace) as folder:
            output = Path(folder) / 'output.wav'
            self.run([executable, '--model', str(model), '--output_file', str(output)], text=text)
            if not output.is_file() or output.stat().st_size > MAX_AUDIO:
                raise MediaError('speech_failed')
            try:
                audio = output.read_bytes()
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    if not wav.getnframes():
                        raise MediaError('speech_failed')
            except (OSError, wave.Error, EOFError) as exc:
                raise MediaError('speech_failed') from exc
            return audio
