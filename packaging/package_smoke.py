"""Explicit packaged self-test: a fresh local home and tiny random fixture, never user models or quality claims."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import httpx


def probe(client: httpx.Client, model: Path, port: int) -> dict:
    result = {}

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    try:
        if request("GET", "/api/health").json().get("ok") is not True:
            raise ValueError("API health failed")
        result["health"] = True
        html = request("GET", "/").text
        scripts = re.findall(r'<script[^>]+src="(/assets/[^"<>]+\.js)"', html)
        if 'id="root"' not in html or not scripts:
            raise ValueError("Bundled web app missing")
        for path in scripts:
            if not request("GET", path).content:
                raise ValueError("Empty UI script")
        result["ui"] = True
        for name, endpoint in (("catalog", "specialists"), ("skills", "skills")):
            if not request("GET", f"/api/{endpoint}").json():
                raise ValueError(f"Bundled {name} missing")
            result[name] = True
        request("PUT", "/api/settings", json={"local_runtime": {
            "model": model.as_posix(), "port": port, "adapters": [], "threads": 1,
            "context": 512, "gpu_layers": 0, "kv_cache_type": "f16"}})
        runtime = request("POST", "/api/runtime/start", json={}).json()
        if runtime.get("running") is not True or runtime.get("base_url") != f"http://127.0.0.1:{port}":
            raise ValueError("Bundled runtime did not start on the requested loopback port")
        answer = request("POST", runtime["base_url"] + "/v1/chat/completions", json={
            "model": "spike-tiny-test", "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 4, "temperature": 0}).json()
        if not answer.get("choices") or "message" not in answer["choices"][0]:
            raise ValueError("No inference response from the random fixture")
        result["inference"] = True
    finally:
        # The launcher's lifespan also stops its owned process if HTTP cleanup itself fails.
        response = client.post("/api/runtime/stop", json={})
        if response.status_code == 200 and response.json().get("running") is False:
            result["runtime_stopped"] = True
    if not result.get("runtime_stopped"):
        raise ValueError("Runtime shutdown failed")
    return result


def run(model: Path, report: Path) -> int:
    from spike.launcher.app import launch

    result = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "quality_measured": False}
    env_keys = ("SPIKE_HOME", "SPIKE_WORKSPACE", "SPIKE_LLAMA_SERVER", "SPIKE_NO_KEYRING")
    previous = {key: os.environ.get(key) for key in env_keys}
    try:
        if not result["frozen"]:
            raise ValueError("Self-test must run from the installed frozen application")
        model = model.resolve(strict=True)
        if model.stat().st_size > 8 * 1024**2 or model.read_bytes()[:4] != b"GGUF":
            raise ValueError("Use only the tiny GGUF integration fixture (at most 8 MiB)")
        result["fixture_sha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
        binary = Path(sys._MEIPASS) / "llama" / ("llama-server.exe" if os.name == "nt" else "llama-server")
        if not binary.is_file():
            raise ValueError("Bundled llama-server missing; a system installation cannot satisfy this test")
        # SQLite handles may remain until process exit on Windows; the CI runner owns this disposable directory.
        with tempfile.TemporaryDirectory(prefix="spike-package-smoke-", ignore_cleanup_errors=True) as folder:
            home = Path(folder)
            os.environ.update(SPIKE_HOME=str(home), SPIKE_WORKSPACE=str(home / "workspace"),
                              SPIKE_LLAMA_SERVER=str(binary), SPIKE_NO_KEYRING="1")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            def window(url, thread):
                with httpx.Client(base_url=url, timeout=90, trust_env=False) as client:
                    result.update(probe(client, model, port))

            try:
                launch(home, window=window)
            finally:
                log = home / "logs/llama-server.log"
                if log.exists():
                    report.with_suffix(".llama.log").write_bytes(log.read_bytes())
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    with suppress(OSError):
        print(json.dumps(result))
    return 0 if result["ok"] else 1
