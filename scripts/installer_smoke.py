"""Installer smoke test without a model (G45): install the built wheel, start SPIKE, check it answers, remove it.

    python scripts/installer_smoke.py --wheel dist/spike_ai-*.whl
    python scripts/installer_smoke.py --use-python /path/to/existing/venv/bin/python

What it does, in a temporary folder that is deleted at the end: makes a venv with the running Python's `venv`
module, `pip install`s the wheel (the normal package index is used for the dependencies, so it needs network
unless they are already cached), starts `spike serve --no-local` on a free loopback port with SPIKE_HOME,
HOME and USERPROFILE pointing into the temporary folder and SPIKE_API_TOKEN set, checks `/api/health` and
`/v1/models`, stops the server, deletes the folder and asserts that the folder is gone and that the real
`~/.spike` is exactly as it was. It never loads a model and never downloads one.

`--use-python` skips the venv and the install and starts the server with an interpreter that already has
SPIKE (for example the development venv): it proves start, check, stop and cleanup, not the install.
It does not replace I3 (the installer tested on real machines) and does not test the signed desktop installers.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVE = "import sys; from spike.cli import main; sys.exit(main(['serve', '--no-local', '--port', sys.argv[1]]))"


class SmokeError(Exception):
    """A check failed; the message says which one."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install the SPIKE wheel in a temp folder, start it, check it, remove it.")
    p.add_argument("--wheel", type=Path, help="the built wheel (dist/*.whl) to install into a fresh venv")
    p.add_argument("--use-python", help="skip the install: start SPIKE with this interpreter, which already has it")
    p.add_argument("--timeout", type=float, default=60, help="seconds to wait for the server to answer (default 60)")
    args = p.parse_args(argv)
    if bool(args.wheel) == bool(args.use_python):
        p.error("give exactly one of --wheel or --use-python")
    return args


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str, token: str = "", timeout: float = 5) -> tuple[int, object]:
    """GET without environment proxies; returns (status, parsed JSON or None)."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def check_health(base: str, timeout: float = 30) -> str:
    """Wait until /api/health answers {"ok": true, "version": ...}; return the version."""
    deadline = time.monotonic() + timeout
    last = "no answer"
    while True:
        try:
            status, body = _get(base + "/api/health", timeout=2)
            if status == 200 and isinstance(body, dict) and body.get("ok") is True and body.get("version"):
                return str(body["version"])
            last = f"HTTP {status}: {body!r}"
        except (OSError, urllib.error.URLError) as exc:
            last = str(exc)
        if time.monotonic() >= deadline:
            raise SmokeError(f"health check failed ({last})")
        time.sleep(0.1)


def check_models(base: str, token: str) -> list[str]:
    status, body = _get(base + "/v1/models", token)
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise SmokeError(f"/v1/models answered HTTP {status}: {body!r}")
    ids = [m.get("id") for m in body["data"] if isinstance(m, dict)]
    if "spike-auto" not in ids:
        raise SmokeError(f"/v1/models does not list spike-auto: {ids}")
    return ids


def check_token_enforced(base: str) -> None:
    status, _ = _get(base + "/v1/models")
    if status != 401:
        raise SmokeError(f"token not enforced: /v1/models without a key answered HTTP {status}, expected 401")


def snapshot(path: Path) -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime_ns) of everything under path; {} when it does not exist."""
    if not path.exists():
        return {}
    out: dict[str, tuple[int, int]] = {".": (0, 0)}
    for p in sorted(path.rglob("*")):
        st = p.lstat()
        out[p.relative_to(path).as_posix()] = (0 if p.is_dir() else st.st_size, 0 if p.is_dir() else st.st_mtime_ns)
    return out


def assert_unchanged(before: dict, after: dict, where: Path) -> None:
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if changed:
        raise SmokeError(f"{where} was modified by the smoke test: {', '.join(changed[:10])}")


def cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    if root.exists():
        raise SmokeError(f"cleanup failed: {root} still exists")


def stop(proc: subprocess.Popen, timeout: float = 20) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout)


def _run(cmd: list[str], env: dict[str, str], what: str) -> None:
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SmokeError(f"{what} failed (exit {done.returncode}):\n{(done.stdout + done.stderr)[-2000:]}")


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(args: argparse.Namespace, root: Path) -> None:
    home = root / "spike-home"
    fake_user = root / "user"
    for d in (home, fake_user):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPIKE_")}
    env.update(SPIKE_HOME=str(home), HOME=str(fake_user), USERPROFILE=str(fake_user), SPIKE_NO_KEYRING="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONUNBUFFERED="1")
    if args.use_python:
        py = args.use_python
        print(f"[1/5] using the existing interpreter {py} (no install)")
    else:
        print("[1/5] creating a venv and installing the wheel (package index used for dependencies)")
        _run([sys.executable, "-m", "venv", str(root / "venv")], env, "venv creation")
        py = str(_venv_python(root / "venv"))
        _run([py, "-m", "pip", "install", "--no-cache-dir", str(args.wheel.resolve())], env, "pip install")
        _run([py, "-c", "import spike, importlib.metadata as m; print(m.version('spike-ai'))"], env, "import spike")
    token, port = secrets.token_hex(16), free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"[2/5] starting SPIKE on {base} with SPIKE_HOME={home}")
    log = (root / "server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([py, "-c", SERVE, str(port)], env={**env, "SPIKE_API_TOKEN": token},
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        if proc.poll() is not None:
            raise SmokeError("the server exited at once")
        version = check_health(base, args.timeout)
        print(f"[3/5] /api/health ok, version {version}")
        ids = check_models(base, token)
        check_token_enforced(base)
        print(f"[4/5] /v1/models ok with the token ({len(ids)} models, spike-auto among them); 401 without it")
    except SmokeError as exc:
        log.flush()
        tail = (root / "server.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise SmokeError(f"{exc}\n--- server log tail ---\n{tail}") from exc
    finally:
        stop(proc)
        log.close()
    if proc.returncode is None:
        raise SmokeError("the server did not stop")
    if not any(home.iterdir()):
        raise SmokeError("the server wrote nothing under SPIKE_HOME: it ran against another folder")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.wheel and not args.wheel.is_file():
        print(f"installer smoke: wheel not found: {args.wheel}", file=sys.stderr)
        return 1
    real = Path.home() / ".spike"
    before = snapshot(real)
    root = Path(tempfile.mkdtemp(prefix="spike-smoke-"))
    try:
        run(args, root)
        cleanup(root)
        assert_unchanged(before, snapshot(real), real)
    except SmokeError as exc:
        print(f"installer smoke FAILED: {exc}", file=sys.stderr)
        shutil.rmtree(root, ignore_errors=True)
        return 1
    print(f"[5/5] stopped, temp folder removed, {real} untouched\ninstaller smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
