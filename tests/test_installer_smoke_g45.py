"""G45: the installer smoke script's offline parts: arguments, health/models checks against a stub, cleanup asserts."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import installer_smoke as smoke  # noqa: E402


class Stub:
    """A loopback server answering like SPIKE: /api/health, /v1/models (Bearer token optional)."""

    def __init__(self, *, token="", health=None, models=None):
        outer = self
        self.token = token
        self.health = {"ok": True, "version": "9.9.9"} if health is None else health
        self.models = {"object": "list", "data": [{"id": "spike-auto"}]} if models is None else models

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):  # noqa: N802
                status, body = 200, None
                if self.path == "/api/health":
                    body = outer.health
                elif self.path == "/v1/models":
                    if outer.token and self.headers.get("Authorization") != f"Bearer {outer.token}":
                        status, body = 401, {"error": {"message": "invalid or missing API key"}}
                    else:
                        body = outer.models
                else:
                    status, body = 404, {}
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    made = []

    def make(**kw):
        made.append(Stub(**kw))
        return made[-1]

    yield make
    for s in made:
        s.close()


def test_arguments_need_exactly_one_source(tmp_path):
    wheel = tmp_path / "spike_ai-0.1.0-py3-none-any.whl"
    assert smoke.parse_args(["--wheel", str(wheel)]).wheel == wheel
    assert smoke.parse_args(["--use-python", sys.executable]).use_python == sys.executable
    for bad in ([], ["--wheel", str(wheel), "--use-python", sys.executable]):
        with pytest.raises(SystemExit):
            smoke.parse_args(bad)


def test_free_port_is_a_usable_loopback_port():
    port = smoke.free_port()
    assert 1024 <= port <= 65535


def test_health_returns_the_version(stub):
    assert smoke.check_health(stub().url) == "9.9.9"


@pytest.mark.parametrize("health", [{"ok": False, "version": "1"}, {"version": "1"}, {"ok": True}, []])
def test_health_rejects_wrong_answers(stub, health):
    with pytest.raises(smoke.SmokeError, match="health"):
        smoke.check_health(stub(health=health).url, timeout=0.3)


def test_health_fails_when_nothing_listens():
    port = smoke.free_port()
    with pytest.raises(smoke.SmokeError, match="health"):
        smoke.check_health(f"http://127.0.0.1:{port}", timeout=0.2)


def test_models_lists_spike_auto_and_enforces_the_token(stub):
    s = stub(token="t0k")
    assert "spike-auto" in smoke.check_models(s.url, "t0k")
    with pytest.raises(smoke.SmokeError, match="models"):
        smoke.check_models(s.url, "wrong")


def test_models_without_token_when_none_is_required(stub):
    assert smoke.check_models(stub().url, "") == ["spike-auto"]


def test_models_rejects_a_list_without_spike_auto(stub):
    with pytest.raises(smoke.SmokeError, match="spike-auto"):
        smoke.check_models(stub(models={"object": "list", "data": []}).url, "")


def test_token_is_enforced_check(stub):
    smoke.check_token_enforced(stub(token="t0k").url)  # 401 without the key: fine
    with pytest.raises(smoke.SmokeError, match="token"):
        smoke.check_token_enforced(stub().url)  # open when a token was configured: not fine


def test_snapshot_detects_additions_changes_and_removals(tmp_path):
    home = tmp_path / ".spike"
    assert smoke.snapshot(home) == {}
    smoke.assert_unchanged(smoke.snapshot(home), smoke.snapshot(home), home)
    home.mkdir()
    before = smoke.snapshot(home)
    (home / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(smoke.SmokeError, match="a.txt"):
        smoke.assert_unchanged(before, smoke.snapshot(home), home)
    mid = smoke.snapshot(home)
    (home / "a.txt").write_text("xyz", encoding="utf-8")
    with pytest.raises(smoke.SmokeError, match="a.txt"):
        smoke.assert_unchanged(mid, smoke.snapshot(home), home)
    (home / "a.txt").unlink()
    with pytest.raises(smoke.SmokeError, match="a.txt"):
        smoke.assert_unchanged(mid, smoke.snapshot(home), home)


def test_cleanup_removes_the_folder_and_asserts_it_is_gone(tmp_path):
    root = tmp_path / "smoke"
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "venv" / "lib" / "x.py").write_text("1", encoding="utf-8")
    smoke.cleanup(root)
    assert not root.exists()
    smoke.cleanup(root)  # idempotent


def test_cleanup_fails_loudly_when_something_stays(tmp_path, monkeypatch):
    root = tmp_path / "smoke"
    root.mkdir()
    monkeypatch.setattr(smoke.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(smoke.SmokeError, match="still exists"):
        smoke.cleanup(root)


def test_stop_terminates_a_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    smoke.stop(child, timeout=10)
    assert child.poll() is not None


def test_main_reports_a_missing_wheel(tmp_path, capsys):
    assert smoke.main(["--wheel", str(tmp_path / "nope.whl")]) == 1
    assert "wheel" in capsys.readouterr().err
