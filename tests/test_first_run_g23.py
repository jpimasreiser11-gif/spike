"""G23 — First-run & installer without real model:
1. First run without model
2. Offline (no network)
3. Simulated low disk
4. Download interrupted midway and resumed
5. Mismatched SHA-256
Plus recovery paths: retry/resume, external API provider with ScriptedProvider, and local .gguf import.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.launcher.setup import Setup
from spike.runtime import models
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text


@pytest.fixture
def launcher_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([text("Respuesta desde proveedor externo guionizado.")], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    app = create_app(state, allowed_hosts={"testserver", "127.0.0.1"})
    app.state.launcher_enabled = True
    app.state.launcher_quit = lambda: None
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, state, app


def test_case_1_first_run_without_model_and_continue_with_external_api(launcher_env) -> None:
    client, _, _ = launcher_env
    res = client.get("/api/setup")
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is True
    assert data["complete"] is False
    assert data["has_local_model"] is False
    assert "es" in data["messages"] and "en" in data["messages"]
    assert "modelo local" in data["messages"]["es"].lower()
    assert "local model" in data["messages"]["en"].lower()

    # User chooses to continue with an external/scripted provider without downloading a local model
    conv = client.post("/api/conversations", json={"title": "Sin modelo local"}).json()
    chat_res = client.post(
        "/api/chat",
        json={"conversation_id": conv["id"], "message": "Hola sin modelo local"},
    )
    assert chat_res.status_code == 200
    assert "Respuesta desde proveedor externo guionizado." in chat_res.text


async def test_case_2_offline_gives_bilingual_message_and_allows_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = SimpleNamespace(
        home=tmp_path,
        update_settings=lambda patch: None,
        settings=lambda: {"local_runtime": {}},
    )
    setup = Setup(state)

    def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network is unreachable", request=request)

    orig_client = httpx.AsyncClient
    monkeypatch.setattr(
        "spike.runtime.models.httpx.AsyncClient",
        lambda **kw: orig_client(transport=httpx.MockTransport(offline_handler)),
    )
    await setup.install([])
    assert setup.job["status"] == "failed"
    assert setup.job["reason"] == "offline"
    assert "conexión" in setup.job["message"]["es"].lower() or "red" in setup.job["message"]["es"].lower()
    assert "connection" in setup.job["message"]["en"].lower() or "network" in setup.job["message"]["en"].lower()
    assert not setup.complete()


def test_case_3_simulated_low_disk_blocks_download_with_bilingual_message(
    launcher_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, app = launcher_env
    client.get("/api/setup")
    setup = app.state.model_setup

    monkeypatch.setattr(
        "spike.launcher.setup.shutil.disk_usage",
        lambda _: SimpleNamespace(total=10 * 1024**3, used=9 * 1024**3, free=512 * 1024**2),
    )
    status = client.get("/api/setup").json()
    assert status["can_download"] is False
    assert status["low_disk"] is True
    assert "disco" in status["messages"]["es"].lower()
    assert "disk" in status["messages"]["en"].lower()

    dl = client.post("/api/setup/download", json={"specialists": []})
    assert dl.status_code == 409
    assert setup.job["reason"] == "disk"
    assert "disco" in setup.job["message"]["es"].lower()
    assert "disk" in setup.job["message"]["en"].lower()


async def test_case_4_interrupted_download_midway_and_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"GGUF" + b"x" * 4096
    digest = hashlib.sha256(payload).hexdigest()
    filename = models.MODELS["qwen3.5-4b"].filename("Q4_K_M")
    half = len(payload) // 2
    saved_settings: dict = {"local_runtime": {}}

    state = SimpleNamespace(
        home=tmp_path,
        update_settings=lambda patch: saved_settings.update(patch),
        settings=lambda: saved_settings,
    )
    setup = Setup(state)
    attempt = {"n": 0}
    range_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/tree/" in request.url.path:
            return httpx.Response(
                200,
                json=[{"path": filename, "lfs": {"size": len(payload), "oid": digest}}],
            )
        if "/api/models/" in request.url.path:
            return httpx.Response(200, json={"cardData": {"license": "apache-2.0"}})
        attempt["n"] += 1
        rng = request.headers.get("Range")
        range_headers.append(rng)
        if attempt["n"] == 1:
            # Cut the download halfway: return only half the bytes so size check detects incomplete transfer
            return httpx.Response(
                200,
                content=payload[:half],
                headers={"content-length": str(len(payload))},
            )
        assert rng == f"bytes={half}-"
        return httpx.Response(
            206,
            content=payload[half:],
            headers={
                "content-range": f"bytes {half}-{len(payload) - 1}/{len(payload)}",
                "content-length": str(len(payload) - half),
            },
        )

    orig_client = httpx.AsyncClient
    monkeypatch.setattr(
        "spike.runtime.models.httpx.AsyncClient",
        lambda **kw: orig_client(transport=httpx.MockTransport(handler)),
    )

    # First attempt: interrupted midway
    await setup.install([])
    assert setup.job["status"] == "failed"
    assert setup.job["reason"] == "interrupted"
    assert setup.job["resumable"] is True
    assert "reanudar" in setup.job["message"]["es"].lower()
    assert "resume" in setup.job["message"]["en"].lower()
    part_file = tmp_path / "models" / f"{filename}.part"
    assert part_file.is_file() and part_file.stat().st_size == half

    # Second attempt: resumes from byte offset `half` and finishes cleanly
    await setup.install([])
    assert setup.job["status"] == "done"
    assert setup.complete() is True
    assert range_headers == [None, f"bytes={half}-"]
    final_file = tmp_path / "models" / filename
    assert final_file.read_bytes() == payload


async def test_case_5_sha256_mismatch_discards_part_and_reports_bilingual_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"GGUF-corrupted-payload"
    expected_digest = "a" * 64
    filename = models.MODELS["qwen3.5-4b"].filename("Q4_K_M")

    state = SimpleNamespace(
        home=tmp_path,
        update_settings=lambda patch: None,
        settings=lambda: {"local_runtime": {}},
    )
    setup = Setup(state)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/tree/" in request.url.path:
            return httpx.Response(
                200,
                json=[{"path": filename, "lfs": {"size": len(payload), "oid": expected_digest}}],
            )
        if "/api/models/" in request.url.path:
            return httpx.Response(200, json={"cardData": {"license": "apache-2.0"}})
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    orig_client = httpx.AsyncClient
    monkeypatch.setattr(
        "spike.runtime.models.httpx.AsyncClient",
        lambda **kw: orig_client(transport=httpx.MockTransport(handler)),
    )

    await setup.install([])
    assert setup.job["status"] == "failed"
    assert setup.job["reason"] == "checksum"
    assert setup.job["resumable"] is False
    assert "sha-256" in setup.job["message"]["es"].lower()
    assert "sha-256" in setup.job["message"]["en"].lower()
    assert not (tmp_path / "models" / f"{filename}.part").exists()
    assert not (tmp_path / "models" / filename).exists()
    assert not setup.complete()


def test_recovery_by_importing_local_gguf_file(launcher_env, tmp_path: Path) -> None:
    client, state, _ = launcher_env
    local_gguf = tmp_path / "incoming" / "custom-local.gguf"
    local_gguf.parent.mkdir(parents=True, exist_ok=True)
    content = b"GGUF\x00\x00\x00\x03local-test-weights"
    local_gguf.write_bytes(content)
    good_sha = hashlib.sha256(content).hexdigest()
    bad_sha = "f" * 64

    # 1. Wrong SHA-256 is rejected with a clear message
    bad_res = client.post(
        "/api/setup/import",
        json={"path": str(local_gguf), "sha256": bad_sha},
    )
    assert bad_res.status_code == 400
    detail = bad_res.json()["detail"]
    assert "sha-256" in detail["es"].lower() and "sha-256" in detail["en"].lower()

    # 2. Valid local .gguf import succeeds and marks setup complete
    ok_res = client.post(
        "/api/setup/import",
        json={"path": str(local_gguf), "sha256": good_sha},
    )
    assert ok_res.status_code == 200
    status = client.get("/api/setup").json()
    assert status["complete"] is True
    assert status["has_local_model"] is True
    assert Path(state.settings()["local_runtime"]["model"]).is_file()


def test_failure_reasons_tell_a_denied_file_permission_from_a_license() -> None:
    license_exc = PermissionError("org/repo has license 'other', which is not on SPIKE's allowlist")
    assert Setup._classify_failure(license_exc, 0) == ("license", False)
    assert Setup._classify_failure(PermissionError(13, "Permission denied"), 0) == ("failed", False)
    assert Setup._classify_failure(ValueError("checksum mismatch for base.gguf"), 0) == ("checksum", False)
    assert Setup._classify_failure(httpx.ConnectError("no route"), 0) == ("offline", False)
    assert Setup._classify_failure(httpx.ReadError("cut"), 1024) == ("interrupted", True)
