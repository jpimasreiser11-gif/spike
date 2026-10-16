#!/usr/bin/env python3
"""Real local CPU embedding smoke; not a routing quality evaluation.

Uses an existing SHA-256 approved GGUF, an ephemeral loopback llama-server
without network downloads, and records only dimension/norm/similarity/RSS.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
from urllib.error import URLError, HTTPError

from http_probe import fetch_json, git_value, host_ram_bytes
from rss_monitor import RSSMonitor

ROOT = Path(__file__).resolve().parents[2]
PHRASES = [
    "query: How to calculate a quarterly financial report?",
    "query: How can I reconcile a company's annual balance?",
    "query: Explain how to test a Python function.",
]


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for part in iter(lambda: fh.read(4_194_304), b""):
            h.update(part)
    return h.hexdigest()


def norm(vector):
    if not isinstance(vector, list) or not vector or len(vector) > 10000:
        raise ValueError("embedding vacío/tamaño inválido")
    if any(type(number) not in (float, int) or not math.isfinite(number) for number in vector):
        raise ValueError("embedding valores no finitos")
    magnitude = math.sqrt(sum(float(number) ** 2 for number in vector))
    if not magnitude:
        raise ValueError("embedding con norma cero")
    return [number / magnitude for number in vector]


def get_embedding(opener, base, model, text, timeout):
    import urllib.request
    body = json.dumps({"model": model, "input": text}).encode()
    request = urllib.request.Request(base + "/v1/embeddings", data=body, method="POST",
                                    headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("respuesta demasiado grande")
    value = json.loads(raw)
    rows = value.get("data") if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("respuesta de embedding inválida")
    embedding = rows[0].get("embedding")
    return norm(embedding)


def main():
    parser = argparse.ArgumentParser(description="Loopback-only CPU embeddings diagnostic; no accuracy claim")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.timeout < 5 or args.timeout > 300:
        parser.error("timeout 5..300")
    now = datetime.now(timezone.utc)
    output = args.output or ROOT / "reports" / "phase0" / (
        "embedding-smoke-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "spike.phase0.embedding-smoke.v1",
        "timestamp_utc": now.isoformat(), "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": bool(git_value("status", "--porcelain")),
        "system": platform.platform(), "host_ram_bytes": host_ram_bytes(),
        "status": "FAIL", "gate_passed": False, "error": None,
        "limitations": "3 original English smoke prompts, not licensed labeled 300+ prompts; does not test routing/Planner. Mac 36GB not 16GB CPU target.",
    }
    proc = None
    monitor = None
    try:
        model_path = args.model.resolve()
        if args.model.is_symlink() or not model_path.is_file() or model_path.suffix != ".gguf":
            raise ValueError("GGUF faltante o symlink")
        actual_hash = hash_file(model_path)
        record["model"] = {"filename": model_path.name, "sha256": actual_hash,
                           "repo_revision_declared": args.upstream_revision,
                           "bytes": model_path.stat().st_size}
        if actual_hash != args.sha256:
            raise ValueError("SHA256 no coincide con el manifest")
        server = shutil.which("llama-server")
        if not server:
            raise RuntimeError("llama-server no instalado")
        record["runtime_version"] = subprocess.check_output([server, "--version"],
                                                             text=True, stderr=subprocess.STDOUT).strip()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        command = [server, "--model", str(model_path), "--host", "127.0.0.1",
                   "--port", str(port), "--embedding", "--pooling", "mean",
                   "--n-gpu-layers", "0", "--ctx-size", "1024",
                   "--parallel", "1", "--threads", "8", "--cache-ram", "0", "--no-webui", "--no-mmproj"]
        logfile = output.with_suffix(".llama.log")
        with logfile.open("x", encoding="utf-8") as handle:
            proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
            monitor = RSSMonitor(proc.pid, interval=0.1)
            monitor.start()
            opener = build_opener(ProxyHandler({}))
            start = time.perf_counter()
            while time.perf_counter() - start < args.timeout:
                if proc.poll() is not None:
                    raise RuntimeError(f"llama-server exit {proc.returncode}; inspect local log {logfile.name}")
                try:
                    ready = fetch_json(opener, url + "/health", 3)
                    if ready.get("status") == "ok":
                        break
                except (URLError, HTTPError, TimeoutError, ValueError):
                    pass
                time.sleep(0.2)
            else:
                raise TimeoutError("server embedding start timed out")
            models = fetch_json(opener, url + "/v1/models", 5)
            served = models.get("data")
            if not isinstance(served, list) or len(served) != 1 or not served[0].get("id"):
                raise RuntimeError("missing unique embedding model ID")
            model_id = served[0]["id"]
            vectors = [get_embedding(opener, url, model_id, p, args.timeout) for p in PHRASES]
            if len({len(v) for v in vectors}) != 1:
                raise RuntimeError("inconsistent embedding dimensionality")
            similarity = lambda a, b: sum(x * y for x, y in zip(a, b))
            record["observation"] = {
                "vectors_count": len(vectors), "dimension": len(vectors[0]),
                "same_domain_cosine": round(similarity(vectors[0], vectors[1]), 8),
                "cross_domain_cosine": round(similarity(vectors[0], vectors[2]), 8),
                "server_model_id_sha256": hashlib.sha256(model_id.encode()).hexdigest(),
                "cpu_layers_requested": 0,
            }
            record["status"] = "OBSERVED_REAL_LOCAL_EMBEDDINGS_NO_ROUTING_GATE"
    except (OSError, ValueError, RuntimeError, TimeoutError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if monitor:
            record["memory"] = monitor.finish()
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(record["status"], output)
    if record.get("error"):
        print(record["error"], file=sys.stderr)
    return 0 if record["status"] == "OBSERVED_REAL_LOCAL_EMBEDDINGS_NO_ROUTING_GATE" else 1


if __name__ == "__main__":
    sys.exit(main())
