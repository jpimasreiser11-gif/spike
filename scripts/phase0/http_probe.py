#!/usr/bin/env python3
"""Smoke HTTP real y TTFT SSE para llama-server existente. Solo stdlib."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "Reply with exactly one word: READY"


def git_value(*args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True,
            text=True, timeout=5, check=True,
        )
        return completed.stdout.strip()
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None


def host_ram_bytes():
    try:
        if platform.system() == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        if platform.system() == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return None


def fetch_json(opener, url, timeout):
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        content = response.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("respuesta JSON demasiado grande")
    return json.loads(content)


def run_probe(args, record):
    parts = urlsplit(args.url)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1")
            or parts.path not in ("", "/") or parts.username or parts.password
            or parts.query or parts.fragment or parts.port is None):
        raise ValueError("--url debe ser http://127.0.0.1:PUERTO o localhost/::1, sin ruta")

    base_url = args.url.rstrip("/")
    opener = build_opener(ProxyHandler({}))  # Nunca usar proxies ni servicios remotos.

    health = fetch_json(opener, base_url + "/health", args.timeout)
    record["server"]["health"] = health
    if isinstance(health, dict) and health.get("status") not in (None, "ok"):
        raise RuntimeError("servidor todavía no disponible: " + str(health.get("status")))

    models = fetch_json(opener, base_url + "/v1/models", args.timeout)
    ids = [m["id"] for m in models.get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str)]
    if not ids:
        raise RuntimeError("/v1/models no devolvió un ID de modelo real")
    if args.expected_model:
        if args.expected_model not in ids:
            raise RuntimeError("modelo esperado no coincide con /v1/models: " + repr(ids))
        model_id = args.expected_model
    elif len(ids) == 1:
        model_id = ids[0]
    else:
        raise RuntimeError("varios modelos; indicar --expected-model: " + repr(ids))
    record["server"]["model_id"] = model_id

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "seed": 42,
        "max_tokens": args.max_tokens,
        "stream": True,
        "cache_prompt": False,
    }
    if args.lora_id is not None:
        payload["lora"] = [{"id": args.lora_id, "scale": 1.0}]

    req = Request(
        base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    start = time.perf_counter()
    first_content_at = None
    first_channel = None
    chunks = 0
    done = False
    visible_parts = []
    reasoning_parts = []
    with opener.open(req, timeout=args.timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            raise RuntimeError("endpoint no devolvió SSE: " + content_type)
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                done = True
                break
            if not data:
                continue
            event = json.loads(data)
            if event.get("error"):
                raise RuntimeError("error SSE: " + str(event["error"]))
            for choice in event.get("choices", []):
                delta = choice.get("delta") or {}
                for field in ("content", "reasoning_content"):
                    text = delta.get(field)
                    if isinstance(text, str) and text:
                        chunks += 1
                        if field == "content":
                            visible_parts.append(text)
                        else:
                            reasoning_parts.append(text)
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                            first_channel = field

    record["measurement"]["total_ms"] = round((time.perf_counter() - start) * 1000, 3)
    record["measurement"]["nonempty_delta_chunks"] = chunks
    record["measurement"]["stream_done"] = done
    visible = "".join(visible_parts)
    reasoning = "".join(reasoning_parts)
    record["measurement"]["visible_response_preview"] = visible[:240]
    record["measurement"]["visible_response_sha256"] = hashlib.sha256(visible.encode()).hexdigest() if visible else None
    record["measurement"]["reasoning_sha256"] = hashlib.sha256(reasoning.encode()).hexdigest() if reasoning else None
    if first_content_at is not None:
        record["measurement"]["ttft_ms"] = round((first_content_at - start) * 1000, 3)
        record["measurement"]["first_delta_field"] = first_channel
    if not done or first_content_at is None:
        raise RuntimeError("stream no completado o sin contenido generado; TTFT no verificado")
    record["status"] = "PASS_HTTP_SMOKE_ONLY"


def main():
    parser = argparse.ArgumentParser(description="Smoke real de llama-server local, sin modelos ni descargas")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", help="ruta JSON; por defecto reports/phase0 con nombre único")
    parser.add_argument("--expected-model", help="ID EXACTO de /v1/models; rechaza otro modelo")
    parser.add_argument("--lora-id", type=int, help="ID de adaptador cargado; solo selección por petición")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.max_tokens < 1 or not 0 < args.timeout <= 300 or (args.lora_id is not None and args.lora_id < 0):
        parser.error("max-tokens > 0, timeout entre 0 y 300, y lora-id >= 0")

    now = datetime.now(timezone.utc)
    output = Path(args.output) if args.output else ROOT / "reports" / "phase0" / ("http-smoke-" + now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(os.getpid()) + ".json")
    revision = git_value("rev-parse", "--verify", "HEAD")
    dirty = git_value("status", "--porcelain")
    record = {
        "schema": "spike.phase0.http-smoke.v1",
        "status": "FAIL",
        "timestamp_utc": now.isoformat(),
        "git_commit": revision,
        "git_dirty": bool(dirty) if dirty is not None else None,
        "client": {"os": platform.platform(), "architecture": platform.machine(),
                   "logical_cpus": os.cpu_count(), "ram_bytes": host_ram_bytes()},
        "server": {"url": args.url, "health": None, "model_id": None},
        "request": {"prompt": PROMPT, "max_tokens": args.max_tokens,
                    "seed": 42, "temperature": 0, "cache_prompt": False,
                    "requested_lora_id": args.lora_id},
        "measurement": {"ttft_ms": None, "total_ms": None,
                        "nonempty_delta_chunks": 0, "stream_done": False,
                        "first_delta_field": None, "visible_response_preview": None,
                        "visible_response_sha256": None, "reasoning_sha256": None},
        "error": None,
    }
    try:
        run_probe(args, record)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as fp:
            json.dump(record, fp, indent=2, ensure_ascii=False)
            fp.write("\n")
    except OSError as exc:
        print(f"FAIL: imposible escribir JSON sin sobrescribir: {exc}", file=sys.stderr)
        return 1

    print(f"{record['status']}: {output}")
    if record["error"]:
        print(record["error"], file=sys.stderr)
    return 0 if record["status"] == "PASS_HTTP_SMOKE_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
