"""One local application per SPIKE_HOME. The web server owns and closes its inference children.

The listening socket remains reserved from port selection until uvicorn takes it over. An OS lock, rather
than a PID file, survives crashes without a stale-lock workaround. Closing the native window, Quit in the
browser UI, or Ctrl-C requests uvicorn's graceful shutdown and runs the application's lifespan cleanup.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import uvicorn


class Instance:
    """A nonblocking OS lock; keep the lock file so two waiters cannot lock different inodes."""

    def __init__(self, home: Path):
        self.path = home / "launcher.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, os.SEEK_END)
                if not self.file.tell():
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("SPIKE ya está abierto / SPIKE is already running") from exc
        return self

    def __exit__(self, *_):
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def wait_healthy(url: str, thread: threading.Thread, timeout: float = 30) -> None:
    """Open no UI before this server answers health; never use environment HTTP proxies for loopback."""
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError("El servidor terminó / The server exited")
            try:
                response = client.get(url + "/api/health")
                if response.status_code == 200 and response.json().get("ok") is True:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.05)
    raise TimeoutError("El servidor no responde / Server health timed out")


def open_window(url: str, thread: threading.Thread, *, webview="auto") -> None:
    if webview == "auto":
        try:
            webview = importlib.import_module("webview")
        except ImportError:
            webview = None
    if webview is not None:
        try:
            native = webview.create_window("SPIKE", url)
            if native is not None:
                def close_after_server():
                    thread.join()
                    with suppress(Exception):  # the user may already have closed the native window
                        native.destroy()
                threading.Thread(target=close_after_server, name="spike-window-close", daemon=True).start()
            webview.start()
            return
        except Exception:
            # Missing native GUI backend (e.g. headless Linux): the same server remains usable in a browser.
            pass
    webbrowser.open(url)
    thread.join()  # browser tabs have no reliable close event; the UI's Quit button stops uvicorn


def desktop_lifecycle(app) -> None:
    """Keep inference cleanup on the server's event loop, before the original application cleanup."""
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def desktop_lifespan(app):
        async with lifespan(app):
            try:
                yield
            finally:
                try:
                    await app.state.spike.stop_runtime()
                finally:
                    pending = list(app.state.spike._background)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

    app.router.lifespan_context = desktop_lifespan


def launch(home: Path, *, server_factory=None, app_factory=None, window=open_window, health=wait_healthy) -> None:
    from spike.server.app import create_app

    with Instance(home), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        app = (app_factory or (lambda: create_app(allowed_hosts={"127.0.0.1"})))()
        if app_factory is None:
            desktop_lifecycle(app)
        server = (server_factory or (lambda app: uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=sock.getsockname()[1], log_level="warning"))))(app)
        app.state.launcher_enabled = True
        app.state.launcher_quit = lambda: setattr(server, "should_exit", True)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="spike-http")
        try:
            thread.start()
            url = f"http://127.0.0.1:{sock.getsockname()[1]}"
            health(url, thread, 30)
            window(url, thread)
        finally:
            server.should_exit = True
            thread.join()  # lifespan closes runtime, embedding server and background downloads before lock release


def main() -> None:
    from spike.runtime.paths import spike_home

    bundled = Path(getattr(sys, "_MEIPASS", "")) / "llama" / (
        "llama-server.exe" if os.name == "nt" else "llama-server")
    if getattr(sys, "frozen", False) and bundled.is_file():
        os.environ.setdefault("SPIKE_LLAMA_SERVER", str(bundled))
    try:
        launch(spike_home())
    except KeyboardInterrupt:
        pass
    except (RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
