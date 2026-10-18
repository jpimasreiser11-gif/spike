"""`spike doctor --strict` (the installers rely on its exit code) and what `spike models pull` says it checked."""

import hashlib
import io
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from spike.cli import main
from spike.runtime import models
from spike.server.state import DEFAULT_SETTINGS


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    return tmp_path


def engine(monkeypatch, found: bool) -> Path:
    path = Path("/usr/bin/llama-server")
    monkeypatch.setattr("spike.runtime.llamacpp_server.find_binary", lambda explicit=None: path if found else None)
    return path


def add_model(home: Path) -> None:
    (home / "models").mkdir(exist_ok=True)
    (home / "models" / "tiny.gguf").write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 0))  # a header, no metadata


def test_doctor_exits_0_without_strict_even_when_nothing_is_installed(home, monkeypatch, capsys):
    engine(monkeypatch, found=False)
    assert main(["doctor"]) == 0
    assert "not found" in capsys.readouterr().out


def test_doctor_strict_needs_llama_server_and_a_model(home, monkeypatch, capsys):
    engine(monkeypatch, found=False)
    assert main(["doctor", "--strict"]) == 1
    err = capsys.readouterr().err
    assert "llama-server was not found" in err and "no local model" in err
    engine(monkeypatch, found=True)
    assert main(["doctor", "--strict"]) == 1
    err = capsys.readouterr().err
    assert "llama-server" not in err and "no local model" in err
    add_model(home)
    assert main(["doctor", "--strict"]) == 0
    assert capsys.readouterr().err == ""


def test_doctor_strict_no_model_check_still_needs_llama_server(home, monkeypatch, capsys):
    engine(monkeypatch, found=True)
    assert main(["doctor", "--strict", "--no-model-check"]) == 0
    engine(monkeypatch, found=False)
    assert main(["doctor", "--strict", "--no-model-check"]) == 1
    assert "no local model" not in capsys.readouterr().err


def test_doctor_strict_json_keeps_stdout_parseable(home, monkeypatch, capsys):
    engine(monkeypatch, found=False)
    assert main(["doctor", "--strict", "--json"]) == 1
    out, err = capsys.readouterr()
    assert json.loads(out)["llama_server"] == "not found" and "llama-server was not found" in err


def test_doctor_does_not_crash_on_a_console_that_cannot_print_unicode(home):
    """A GitHub windows runner prints through cp1252: doctor's '≈' used to raise UnicodeEncodeError there."""
    add_model(home)
    env = {**os.environ, "SPIKE_HOME": str(home), "SPIKE_NO_KEYRING": "1", "PYTHONIOENCODING": "cp1252"}
    run = subprocess.run([sys.executable, "-m", "spike.cli", "doctor"], env=env, capture_output=True, timeout=120)
    err = run.stderr.decode("cp1252", "replace")
    assert run.returncode == 0 and "Traceback" not in err, err
    model_line = next(ln for ln in run.stdout.decode("cp1252").splitlines() if "model tiny.gguf" in ln)
    assert "tokens ? " in model_line  # the '≈' became '?', the rest of the line is intact


def test_utf8_streams_are_left_alone():
    from spike.cli import _never_crash_on_output

    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    real, sys.stdout = sys.stdout, stream
    try:
        _never_crash_on_output()
    finally:
        sys.stdout = real
    assert stream.errors == "strict"


def hub(sha256: str | None, body: bytes = b"weights") -> httpx.AsyncClient:
    """A Hub that serves one file, with or without the hash it normally gives for Git LFS files."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/tree/main"):
            lfs = {"oid": sha256, "size": len(body)} if sha256 else {}
            return httpx.Response(200, json=[{"path": "Qwen3.5-2B-Q4_K_M.gguf", "size": len(body), "lfs": lfs}])
        if path.startswith("/api/models/"):
            return httpx.Response(200, json={"cardData": {"license": "apache-2.0"}})
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_download_says_whether_the_hub_hash_was_checked(tmp_path):
    body = b"weights"
    digest = hashlib.sha256(body).hexdigest()
    path, verified = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(digest))
    assert path.read_bytes() == body and verified
    again, verified = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(digest))
    assert again == path and verified  # already there with the right hash

    path.unlink()
    path, verified = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(None))
    assert path.read_bytes() == body and not verified

    path.unlink()
    with pytest.raises(ValueError, match="checksum mismatch"):
        await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub("0" * 64))
    assert not path.exists()


@pytest.mark.parametrize(("verified", "said"), [(True, "(sha256 verified)"), (False, "gave no SHA-256 to check")])
def test_models_pull_only_claims_a_checksum_when_one_was_checked(home, monkeypatch, capsys, verified, said):
    async def fake_download(model_id, quant=None, progress=None):
        return home / "models" / "m.gguf", verified

    monkeypatch.setattr(models, "download", fake_download)
    assert main(["models", "pull"]) == 0
    out = capsys.readouterr().out
    assert said in out and ("sha256 verified" in out) is verified
    assert "set as the local SPIKE model" in out
    assert not DEFAULT_SETTINGS["local_runtime"]["model"]  # saved in the home's database, not in the shared defaults
