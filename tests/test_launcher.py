"""Desktop lifecycle uses a fake server; model transfers use an in-process HTTP fixture, never the network."""

import hashlib
from types import SimpleNamespace

import httpx
import pytest

from spike.launcher.app import Instance, launch, open_window, wait_healthy
from spike.runtime.models import download_file


@pytest.fixture
def fake_socket(monkeypatch):
    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 0)

        def getsockname(self):
            return ("127.0.0.1", 54321)

    monkeypatch.setattr("spike.launcher.app.socket.socket", lambda *a, **kw: Socket())


@pytest.fixture
def local_http():
    payload = b"verified model bytes"
    requests = []

    def handle(request):
        requests.append(request)
        offset = int(request.headers.get("Range", "bytes=0-")[6:-1])
        headers = {"Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}"} if offset else {}
        return httpx.Response(206 if offset else 200, content=payload[offset:], headers=headers)

    return payload, requests, httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_resume_and_verified_cache(tmp_path, local_http):
    payload, requests, client = local_http
    dest = tmp_path / "model.gguf"
    dest.with_suffix(".gguf.part").write_bytes(payload[:5])
    digest = hashlib.sha256(payload).hexdigest()
    async with client:
        await download_file(client, "https://local.test/model", dest, digest, len(payload))
        await download_file(client, "https://local.test/model", dest, digest, len(payload))
    assert dest.read_bytes() == payload
    assert len(requests) == 1 and requests[0].headers["Range"] == "bytes=5-"


async def test_bad_hash_is_never_installed(tmp_path, local_http):
    _, _, client = local_http
    dest = tmp_path / "model.gguf"
    async with client:
        with pytest.raises(ValueError, match="checksum"):
            await download_file(client, "https://local.test/model", dest, "0" * 64)
    assert not dest.exists() and not dest.with_suffix(".gguf.part").exists()


async def test_ignored_range_restarts(tmp_path):
    dest = tmp_path / "model"
    dest.with_suffix(".part").write_bytes(b"stale")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"good"))) as c:
        await download_file(c, "https://local.test/model", dest, hashlib.sha256(b"good").hexdigest())
    assert dest.read_bytes() == b"good"


def test_instance_lock_recovers_after_release(tmp_path):
    with Instance(tmp_path), pytest.raises(RuntimeError, match="already"), Instance(tmp_path):
        pass
    with Instance(tmp_path):
        pass


def test_fake_server_health_before_window_and_cleanup(tmp_path, fake_socket):
    events = []

    class FakeServer:
        should_exit = False

        def run(self, sockets):
            assert sockets[0].getsockname()[0] == "127.0.0.1"
            events.append("run")
            while not self.should_exit:
                import time
                time.sleep(0.001)
            events.append("closed")

    server = FakeServer()

    def healthy(url, thread, timeout):
        assert url.startswith("http://127.0.0.1:") and thread.is_alive()
        events.append("health")

    def window(url, thread):
        assert events[-1] == "health"
        events.append("window")

    launch(tmp_path, server_factory=lambda app: server, window=window, health=healthy,
           app_factory=lambda: SimpleNamespace(state=SimpleNamespace()))
    assert events[-2:] == ["window", "closed"] and server.should_exit
    with Instance(tmp_path):
        pass


def test_window_failure_still_stops_server(tmp_path, fake_socket):
    class FakeServer:
        should_exit = False

        def run(self, sockets):
            import time
            while not self.should_exit:
                time.sleep(0.001)

    server = FakeServer()
    with pytest.raises(ValueError):
        launch(tmp_path, server_factory=lambda app: server,
               window=lambda *_: (_ for _ in ()).throw(ValueError()), health=lambda *_: None,
               app_factory=lambda: SimpleNamespace(state=SimpleNamespace()))
    assert server.should_exit


def test_browser_fallback_and_native_window(monkeypatch):
    calls = []
    monkeypatch.setattr("spike.launcher.app.webbrowser.open", lambda url: calls.append(url))
    thread = SimpleNamespace(join=lambda: calls.append("join"))
    open_window("http://127.0.0.1:1", thread, webview=None)
    assert calls == ["http://127.0.0.1:1", "join"]
    native = SimpleNamespace(create_window=lambda *a: calls.append(a), start=lambda: calls.append("start"))
    open_window("http://127.0.0.1:2", thread, webview=native)
    assert calls[-1] == "start"


def test_health_timeout_and_dead_server():
    with pytest.raises(RuntimeError):
        wait_healthy("http://127.0.0.1:1", SimpleNamespace(is_alive=lambda: False), 1)
    with pytest.raises(TimeoutError):
        wait_healthy("http://127.0.0.1:1", SimpleNamespace(is_alive=lambda: True), 0)


async def test_launcher_lifespan_stops_inference_and_cancels_downloads(tmp_path, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from spike.launcher.app import desktop_lifecycle

    state = SimpleNamespace(stop_runtime=AsyncMock(), _background=set())
    events = []

    @asynccontextmanager
    async def original(app):
        yield
        events.append("original-close")

    app = FastAPI(lifespan=original)
    app.state.spike = state
    desktop_lifecycle(app)
    async with app.router.lifespan_context(app):
        task = asyncio.create_task(asyncio.sleep(100))
        state._background.add(task)
        await asyncio.sleep(0)
    state.stop_runtime.assert_awaited_once()
    assert task.cancelled() and events == ["original-close"]


async def test_interrupted_transfer_keeps_partial_for_next_request(tmp_path):
    payload = b"x" * (1 << 20) + b"tail"
    requests = []

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield payload[:1 << 20]
            raise httpx.ReadError("interrupted fixture")

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, stream=Interrupted())
        assert request.headers["Range"] == f"bytes={1 << 20}-"
        return httpx.Response(206, content=b"tail", headers={
            "Content-Range": f"bytes {1 << 20}-{len(payload) - 1}/{len(payload)}"})

    dest = tmp_path / "model"
    digest = hashlib.sha256(payload).hexdigest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.ReadError):
            await download_file(client, "https://local.test/model", dest, digest, len(payload))
        assert dest.with_suffix(".part").stat().st_size == 1 << 20
        await download_file(client, "https://local.test/model", dest, digest, len(payload))
    assert dest.read_bytes() == payload


async def test_complete_partial_needs_no_request_and_invalid_range_cannot_install(tmp_path):
    dest = tmp_path / "model"
    dest.with_suffix(".part").write_bytes(b"done")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(206, content=b"wrong", headers={"Content-Range": "bytes 0-4/5"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await download_file(client, "https://local.test/model", dest, hashlib.sha256(b"done").hexdigest())
        assert dest.read_bytes() == b"done" and not calls
        dest.with_suffix(".part").write_bytes(b"partial")
        with pytest.raises(ValueError, match="Content-Range"):
            await download_file(client, "https://local.test/model", dest, "0" * 64)
        assert dest.read_bytes() == b"done"


async def test_symlink_partial_is_refused(tmp_path):
    dest = tmp_path / "model"
    outside = tmp_path / "other"
    outside.write_bytes(b"preserve")
    try:
        dest.with_suffix(".part").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted by this OS")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"bad"))) as c:
        with pytest.raises(ValueError, match="symlink"):
            await download_file(c, "https://local.test/model", dest, "0" * 64)
    assert outside.read_bytes() == b"preserve"


def test_native_window_closes_when_server_quits():
    import threading

    destroyed = threading.Event()
    native = SimpleNamespace(destroy=destroyed.set)
    gui = SimpleNamespace(create_window=lambda *args: native, start=lambda: destroyed.wait(1))
    open_window("http://127.0.0.1:1", SimpleNamespace(join=lambda: None), webview=gui)
    assert destroyed.is_set()


def test_health_waits_for_successful_json_without_proxy(monkeypatch):
    responses = iter([httpx.Response(503, json={"ok": False}), httpx.Response(200, json={"ok": True})])
    calls = []

    class Client:
        def __init__(self, **kw):
            assert kw["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, url):
            calls.append(url)
            return next(responses)

    monkeypatch.setattr("spike.launcher.app.httpx.Client", Client)
    monkeypatch.setattr("spike.launcher.app.time.sleep", lambda *_: None)
    wait_healthy("http://127.0.0.1:1234", SimpleNamespace(is_alive=lambda: True), 1)
    assert calls == ["http://127.0.0.1:1234/api/health"] * 2
