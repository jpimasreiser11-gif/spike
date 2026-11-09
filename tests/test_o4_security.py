"""O4 security review (docs/audits/2026-11-security-review.md): guards that stay as tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider

SECRET = "sk-o4-probe-7f3a9c1e5b"


def test_no_get_route_log_or_database_returns_a_stored_key(tmp_path: Path, monkeypatch):
    """A provider key and a connector secret, stored through the API, never come back from any GET route without
    path parameters (/api, /v1, /mcp), and are not in the database or a log: only in the key store."""
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")

    def factory(cfg):
        provider = ScriptedProvider([], name=cfg.id)
        provider.config = cfg
        return provider

    client = TestClient(create_app(AppState(home=tmp_path, provider_factory=factory)))
    assert client.post("/api/providers", json={"preset": "deepseek", "api_key": SECRET, "model": "deepseek-chat"}
                       ).status_code == 200
    listed = client.get("/api/connectors").json()
    connectors = listed if isinstance(listed, list) else listed.get("connectors", [])
    with_secret = next(c for c in connectors if c.get("secrets"))
    assert client.put(f"/api/connectors/{with_secret['id']}",
                      json={"secrets": {with_secret["secrets"][0]["name"]: SECRET + "-connector"}}).status_code == 200

    checked = 0
    for route in client.app.routes:
        path, methods = getattr(route, "path", ""), getattr(route, "methods", None) or set()
        if "GET" in methods and "{" not in path and path.startswith(("/api", "/v1", "/mcp")):
            assert SECRET not in client.get(path).text, path
            checked += 1
    assert checked >= 30  # the routes really were walked (34 on 2026-11-09)
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.name != "secrets.json":  # the fallback key store (0600) when there is no OS keychain
            assert SECRET.encode() not in f.read_bytes(), f


import argparse  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.20"])
def test_spike_serve_refuses_a_network_bind_without_allow_network(host, tmp_path, monkeypatch, capsys):
    """The /api app has no login: binding beyond this computer must be asked for by name, not by a stray --host."""
    import uvicorn

    from spike import cli

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.append(kw))
    code = cli.cmd_serve(argparse.Namespace(host=host, port=8740, start_local=False, open=False))
    assert code == 2 and not started
    assert "--allow-network" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_spike_serve_binds_this_computer_without_any_flag(host, tmp_path, monkeypatch):
    import uvicorn

    from spike import cli

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.append(kw))
    cli.cmd_serve(argparse.Namespace(host=host, port=8740, start_local=False, open=False))
    assert started and started[0]["host"] == host
