"""First-run API is opt-in, local-only and never contacts the Hub before Download all."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.launcher.setup import Setup
from spike.server.app import create_app
from spike.server.state import AppState


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "workspace"))
    state = AppState(home=tmp_path)
    app = create_app(state, allowed_hosts={"testserver", "127.0.0.1"})
    app.state.launcher_enabled = True
    app.state.launcher_quit = lambda: None
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, state, app


def test_read_only_status_and_unpublished_specialists(env):
    client, _, _ = env
    data = client.get("/api/setup").json()
    assert data["enabled"] and not data["complete"]
    assert data["disk_free"] > 0 and data["ram_total"] > 0
    assert all(not s["available"] for s in data["specialists"])
    assert client.post("/api/setup/download", json={"specialists": ["medicine"]}).status_code == 400


def test_disabled_and_cross_origin_requests_cannot_download(env):
    client, _, app = env
    assert client.post("/api/setup/download", json={}, headers={"Origin": "https://evil.test"}).status_code == 403
    app.state.launcher_enabled = False
    assert client.get("/api/setup").json() == {"enabled": False}
    assert client.post("/api/setup/download", json={}).status_code == 404


async def test_download_requires_hash_and_records_only_success(tmp_path, monkeypatch):
    state = SimpleNamespace(home=tmp_path, update_settings=lambda patch: None,
                            settings=lambda: {"local_runtime": {}})
    setup = Setup(state)
    fake = AsyncMock(side_effect=ValueError("missing hash"))
    monkeypatch.setattr("spike.launcher.setup.models.download", fake)
    await setup.install([])
    assert setup.job["status"] == "failed" and not setup.complete()
    assert fake.call_args.kwargs["require_hash"] is True
    dest = tmp_path / "models" / "base.gguf"
    dest.parent.mkdir()
    dest.write_bytes(b"base")
    fake.side_effect = None
    fake.return_value = (dest, True)
    await setup.install([])
    assert setup.job["status"] == "done" and setup.complete()
    dest.unlink()
    assert not setup.complete()


async def test_resources_and_concurrent_jobs(env, monkeypatch):
    client, _, app = env
    client.get("/api/setup")
    setup = app.state.model_setup
    monkeypatch.setattr(setup, "resources", lambda *_: {"disk_free": 0, "ram_total": 0, "ram_available": 0,
                                                       "required_disk": 4, "required_ram": 8, "can_download": False})
    assert client.post("/api/setup/download", json={}).status_code == 409
    setup.job["status"] = "running"
    assert client.post("/api/setup/download", json={}).status_code == 409


async def test_selected_published_adapter_verified_and_configured(tmp_path, monkeypatch):
    payload = b"adapter"
    cfg = []
    state = SimpleNamespace(home=tmp_path, update_settings=cfg.append, settings=lambda: {"local_runtime": {}})
    artifact = {"repo": "org/repo", "revision": "a" * 40, "filename": "spike-code.gguf", "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "license": "apache-2.0"}
    setup = Setup(state, artifacts={"code": artifact})
    dest = tmp_path / "base.gguf"
    dest.write_bytes(b"base")
    monkeypatch.setattr("spike.launcher.setup.models.download", AsyncMock(return_value=(dest, True)))
    original = httpx.AsyncClient
    monkeypatch.setattr("spike.launcher.setup.httpx.AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload))))
    await setup.install(["code"])
    assert setup.job["status"] == "done"
    assert Path(cfg[-1]["local_runtime"]["adapters"][0]).read_bytes() == payload




@pytest.mark.parametrize("license_id,digest", [("apache-2.0", None), (None, "0" * 64)])
async def test_wizard_base_rejects_missing_license_or_hash_before_transfer(tmp_path, license_id, digest):
    from spike.runtime import models

    requests = []
    filename = models.MODELS["qwen3.5-4b"].filename("Q4_K_M")

    def handle(request):
        requests.append(request)
        if "/tree/" in request.url.path:
            return httpx.Response(200, json=[{"path": filename, "lfs": {"size": 4, "oid": digest}}])
        return httpx.Response(200, json={"cardData": {"license": license_id}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="required"):
            await models.download("qwen3.5-4b", dest_dir=tmp_path, require_hash=True, client=client)
    assert len(requests) == 2 and not list(tmp_path.iterdir())


def test_quit_requires_launcher_and_local_json(env):
    client, _, app = env
    calls = []
    app.state.launcher_quit = lambda: calls.append("quit")
    assert client.post("/api/setup/quit", json={}).status_code == 200
    assert calls == ["quit"]
    assert client.post("/api/setup/quit", content="x", headers={"Content-Type": "text/plain"}).status_code == 403
    assert client.post("/api/setup/quit", json={}, headers={"Origin": "http://testserver:99"}).status_code == 403
    assert calls == ["quit"]
