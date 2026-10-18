"""Lifecycle of the local llama-server process that hosts the SPIKE base model and all specialist adapters."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psutil

from spike.runtime.paths import spike_home


@dataclass
class ServerConfig:
    model: Path
    adapters: list[Path] = field(default_factory=list)
    host: str = "127.0.0.1"
    port: int = 8737
    context: int = 32768
    parallel: int = 1  # one slot: the prompt cache is not keyed by adapter (see providers/llamacpp.py)
    threads: int | None = None
    gpu_layers: int = 0
    kv_cache_type: str = "q8_0"
    flash_attn: str = "auto"
    binary: Path | None = None
    extra_args: list[str] = field(default_factory=list)

    def command(self, binary: Path) -> list[str]:
        cmd = [
            str(binary), "-m", str(self.model), "--host", self.host, "--port", str(self.port),
            "-c", str(self.context), "--parallel", str(self.parallel), "--jinja", "-ngl", str(self.gpu_layers),
            "--flash-attn", self.flash_attn, "--metrics", "--no-webui",
        ]
        if self.kv_cache_type != "f16":
            cmd += ["--cache-type-k", self.kv_cache_type, "--cache-type-v", self.kv_cache_type]
        if self.threads:
            cmd += ["-t", str(self.threads)]
        for adapter in self.adapters:
            cmd += ["--lora", str(adapter)]
        if self.adapters:
            cmd.append("--lora-init-without-apply")
        return cmd + list(self.extra_args)


def find_binary(explicit: Path | None = None) -> Path | None:
    candidates = [explicit] if explicit else []
    env = os.environ.get("SPIKE_LLAMA_SERVER")
    if env:
        candidates.append(Path(env))
    candidates.append(spike_home() / "bin" / ("llama-server.exe" if os.name == "nt" else "llama-server"))
    for c in candidates:
        if c and c.is_file() and os.access(c, os.X_OK):
            return c
    found = shutil.which("llama-server")
    return Path(found) if found else None


class LlamaServer:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = spike_home() / "logs" / "llama-server.log"
        self.started_at: float | None = None
        self.load_seconds: float | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    async def start(self, timeout_s: float = 300.0) -> None:
        if self.running():
            return
        binary = find_binary(self.config.binary)
        if binary is None:
            raise FileNotFoundError(
                "llama-server not found. Install llama.cpp (e.g. `brew install llama.cpp`) or set SPIKE_LLAMA_SERVER."
            )
        if not self.config.model.is_file():
            raise FileNotFoundError(f"model file not found: {self.config.model}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab")
        self.started_at = time.perf_counter()
        self.process = subprocess.Popen(
            self.config.command(binary), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        log.close()
        async with httpx.AsyncClient(timeout=5.0) as client:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"llama-server exited with code {self.process.returncode}; see {self.log_path}")
                try:
                    r = await client.get(self.base_url + "/health")
                    if r.status_code == 200:
                        self.load_seconds = round(time.perf_counter() - self.started_at, 3)
                        if self.config.adapters:
                            await self._disable_adapters_by_default(client)
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        await self.stop()
        raise TimeoutError(f"llama-server did not become healthy within {timeout_s:.0f}s; see {self.log_path}")

    async def _disable_adapters_by_default(self, client: httpx.AsyncClient) -> None:
        """`--lora` loads adapters with global scale 1.0, and requests without an explicit `lora` list use
        the global scales. Set them to 0 so such requests run the plain base model."""
        url = self.base_url + "/lora-adapters"
        loaded = (await client.get(url)).json()
        (await client.post(url, json=[{"id": a["id"], "scale": 0.0} for a in loaded])).raise_for_status()
        if any(a["scale"] != 0.0 for a in (await client.get(url)).json()):
            await self.stop()
            raise RuntimeError("could not reset global LoRA scales to 0")

    async def stop(self, timeout_s: float = 10.0) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            if os.name == "nt":
                self.process.terminate()
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(self.process.wait, timeout_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def memory_rss_mb(self) -> float | None:
        if not self.running():
            return None
        try:
            return round(psutil.Process(self.process.pid).memory_info().rss / 1024**2, 1)
        except psutil.Error:
            return None

    def status(self) -> dict:
        return {
            "running": self.running(),
            "pid": self.process.pid if self.running() else None,
            "base_url": self.base_url,
            "model": str(self.config.model),
            "adapters": [str(a) for a in self.config.adapters],
            "context": self.config.context,
            "load_seconds": self.load_seconds,
            "rss_mb": self.memory_rss_mb(),
            "log": str(self.log_path),
        }
