"""G43: the local error log records unhandled failures anonymised (no paths, messages, file text or keys), rotates
with a size cap, and its routes only read and clear that local file."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike import __version__, errorlog
from spike.jobs import JobQueue
from spike.server.app import create_app
from spike.server.state import AppState

KEY = "sk-live" + "A1b2C3d4E5f6G7h8I9j0K1l2"  # split so the secret scanners of this repo do not flag the test
BODY = "Cliente: Acme Industrial\nFactura 4471: 12.300 EUR\nnotas privadas del contrato"


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home, spike_home = tmp_path / "ana", tmp_path / "data" / "spike-home"
    home.mkdir()
    spike_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SPIKE_HOME", str(spike_home))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    yield home, spike_home
    errorlog.uninstall()


def entries_text(folder: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in errorlog.log_files(folder))


def boom_in(path: Path):
    """A function whose code lives at `path`, so its traceback frame names that file; it raises with a message
    that quotes a key, a file's text and absolute paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    source = ("def boom(body, key, where):\n"
              "    secret = key\n"
              "    raise ValueError(f'cannot parse {where}: {body} (key={secret})')\n")
    path.write_text(source, encoding="utf-8")
    scope: dict = {}
    exec(compile(source, str(path), "exec"), scope)
    return scope["boom"]


def test_anonymise_paths_and_secrets(homes):
    home, spike_home = homes
    text = (f"open {spike_home}/logs/calls.db and {home}/Documents/plan.txt, /srv/clients/acme/report.csv, "
            f"C:\\Users\\ana\\Desktop\\nomina.xlsx, key {KEY}, api_key=abcdef0123456789XYZ "
            "and https://user:pw@api.example.com/v1/chat?api_key=zz99")
    out = errorlog.anonymise(text)
    assert "~/.spike/logs/calls.db" in out and "~/Documents/plan.txt" in out
    assert "…/report.csv" in out and "…\\nomina.xlsx" in out
    for leaked in (str(home), str(spike_home), "/srv", "acme", "Users", KEY, "abcdef0123456789XYZ", "pw@", "zz99"):
        assert leaked not in out, leaked
    assert "https://api.example.com/v1/chat" in out


def test_entry_keeps_no_message_file_body_key_or_absolute_path(homes):
    home, spike_home = homes
    folder = spike_home / "logs"
    errorlog.install(folder)
    boom = boom_in(home / "proj" / "tool.py")
    try:
        boom(BODY, KEY, f"{spike_home}/files/{home.name}.txt")
    except ValueError as exc:
        errorlog.record("job", f"render {spike_home}/x", exc)
    raw = entries_text(folder)
    for leaked in (KEY, "Acme", "Factura", "notas privadas", str(home), str(spike_home), "cannot parse"):
        assert leaked not in raw, leaked
    [entry] = errorlog.read(folder)
    assert entry["kind"] == "job" and entry["type"] == "ValueError" and entry["version"] == __version__
    assert entry["where"] == "render ~/.spike/x"
    assert entry["frames"][-1] == "~/proj/tool.py:3 in boom"
    assert any(f.startswith("tests/test_error_log_g43.py:") for f in entry["frames"])


def test_rotation_keeps_two_backups_under_the_size_cap(homes):
    _, spike_home = homes
    folder = spike_home / "logs"
    errorlog.install(folder, max_bytes=2000, backups=2)
    for i in range(300):
        try:
            raise KeyError(i)
        except KeyError as exc:
            errorlog.record("job", f"render {i}", exc)
    files = sorted(p.name for p in folder.iterdir())
    assert files == ["errors.log", "errors.log.1", "errors.log.2"]
    assert all((folder / f).stat().st_size <= 2000 for f in files)
    entries = errorlog.read(folder, limit=1000)
    assert entries[0]["where"] == "render 299"  # newest first; the oldest were dropped by the cap
    assert 0 < len(entries) < 300


@pytest.fixture
def app_client(homes):
    _, spike_home = homes
    app = create_app(AppState(home=spike_home))

    @app.get("/api/test/boom/{item}")
    async def boom_route(item: str) -> dict:
        raise RuntimeError(f"failed on {spike_home}/files/{item}.txt with {KEY}: {BODY}")

    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the web app's catch-all when web/dist exists
    client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    yield client, spike_home / "logs"


def test_a_500_in_a_route_is_recorded_anonymised(app_client):
    client, folder = app_client
    assert client.get("/api/test/boom/acme-contract").status_code == 500
    assert client.get("/api/health").status_code == 200  # a handled request adds nothing
    entries = client.get("/api/errors").json()["entries"]
    assert len(entries) == 1
    [e] = entries
    assert (e["kind"], e["where"], e["type"]) == ("route", "GET /api/test/boom/{item}", "RuntimeError")
    assert e["frames"][-1].startswith("tests/test_error_log_g43.py:") and e["frames"][-1].endswith(" in boom_route")
    raw = entries_text(folder)
    for leaked in ("acme-contract", KEY, "Factura", str(folder.parent)):
        assert leaked not in raw and leaked not in json.dumps(entries), leaked


def test_routes_only_read_and_clear_the_local_file(app_client, monkeypatch):
    client, folder = app_client
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"time": 1.0, "kind": "route", "where": "GET /api/a", "type": "KeyError", "frames": []},
             {"time": 2.0, "kind": "job", "where": "render /srv/clients/acme/out.mp4", "type": "OSError",
              "frames": ["/opt/build/spike/x.py:1 in f"]}]
    (folder / "errors.log").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")

    def no_network(*args, **kwargs):
        raise AssertionError("the error log must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    body = client.get("/api/errors").json()
    assert [e["where"] for e in body["entries"]] == ["render …/out.mp4", "GET /api/a"]
    assert body["entries"][0]["frames"] == ["…/x.py:1 in f"]
    assert body["path"] == "~/.spike/logs/errors.log"
    text = client.get("/api/errors/report").json()["text"]
    assert f"SPIKE: {__version__}" in text and "Python: " in text and "OS: " in text
    assert "render …/out.mp4" in text and "acme" not in text
    other = TestClient(client.app, client=("192.168.1.20", 50000))
    # reading the log is for this computer too: a server opened to the network does not show it to others
    assert other.get("/api/errors").status_code == 403
    assert other.get("/api/errors/report").status_code == 403
    assert other.delete("/api/errors").status_code == 403
    assert client.delete("/api/errors").json() == {"ok": True}
    assert not errorlog.log_files(folder)
    assert client.get("/api/errors").json()["entries"] == []


def test_background_jobs_and_logged_exceptions_are_recorded(homes):
    _, spike_home = homes
    folder = spike_home / "logs"
    errorlog.install(folder)
    state = AppState(home=spike_home)

    async def fail() -> None:
        raise OSError(2, f"No such file: {spike_home}/media/clip.mp4")

    async def scenario() -> None:
        jobs = JobQueue(available=lambda: 1 << 40)
        jid = jobs.submit("render", fail)
        with pytest.raises(OSError):
            await jobs.wait(jid)
        task = state.background(fail())
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    asyncio.run(scenario())
    try:
        raise ZeroDivisionError("private 42")
    except ZeroDivisionError:
        logging.getLogger("spike.test.g43").exception("export failed for %s", "acme.docx")
    by_kind = {e["kind"]: e for e in errorlog.read(folder)}
    assert by_kind["job"]["where"] == "render" and by_kind["job"]["errno"] == "ENOENT"
    assert by_kind["background"]["where"].endswith("fail")
    assert by_kind["log"]["where"] == "spike.test.g43: export failed for %s"
    assert "clip.mp4" not in entries_text(folder) and "acme" not in entries_text(folder)
