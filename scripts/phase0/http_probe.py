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
from rss_monitor import RSSMonitor

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


def empty_measurement():
    return {"ttft_ms": None, "total_ms": None,
            "nonempty_delta_chunks": 0, "stream_done": False,
            "first_delta_field": None, "visible_response_preview": None,
            "visible_response_sha256": None, "reasoning_sha256": None}


def stream_completion(opener, base_url, model_id, args, prompt, lora_id=None):
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "seed": 42, "max_tokens": args.max_tokens,
        "stream": True, "cache_prompt": False,
    }
    if lora_id is not None:
        payload["lora"] = [{"id": lora_id, "scale": 1.0}]
    req = Request(
        base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    measure = empty_measurement()
    start = time.perf_counter()
    first_content_at = None
    first_channel = None
    visible_parts, reasoning_parts = [], []
    seen_done = False
    bytes_read = 0
    with opener.open(req, timeout=args.timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            raise RuntimeError("endpoint no devolvió SSE: " + content_type)
        for line in response:
            bytes_read += len(line)
            if bytes_read > 8_000_000 or time.perf_counter() - start > args.timeout:
                raise RuntimeError("stream demasiado grande o superó timeout total")
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                seen_done = True
                break
            if not data:
                continue
            event = json.loads(data)
            if not isinstance(event, dict):
                raise RuntimeError("evento SSE debe ser objeto JSON")
            if event.get("error"):
                raise RuntimeError("error SSE: " + str(event["error"]))
            for choice in event.get("choices", []):
                if not isinstance(choice, dict):
                    raise RuntimeError("choice SSE no es objeto")
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise RuntimeError("delta SSE no es objeto")
                for field in ("content", "reasoning_content"):
                    chunk = delta.get(field)
                    if isinstance(chunk, str) and chunk:
                        measure["nonempty_delta_chunks"] += 1
                        (visible_parts if field == "content" else reasoning_parts).append(chunk)
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                            first_channel = field
    measure["total_ms"] = round((time.perf_counter() - start) * 1000, 3)
    measure["stream_done"] = seen_done
    visible = "".join(visible_parts)
    reasoning = "".join(reasoning_parts)
    measure["visible_response_preview"] = visible[:240]
    measure["visible_response_sha256"] = hashlib.sha256(visible.encode()).hexdigest() if visible else None
    measure["reasoning_sha256"] = hashlib.sha256(reasoning.encode()).hexdigest() if reasoning else None
    if first_content_at is not None:
        measure["ttft_ms"] = round((first_content_at - start) * 1000, 3)
        measure["first_delta_field"] = first_channel
    if not seen_done or first_content_at is None:
        raise RuntimeError("stream no completado o sin contenido generado; TTFT no verificado")
    return measure, visible


def available_adapters(opener, base_url, timeout):
    raw = fetch_json(opener, base_url + "/lora-adapters", timeout)
    data = raw if isinstance(raw, list) else raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("/lora-adapters no devolvió lista de adaptadores")
    adapters = {}
    for item in data:
        if isinstance(item, dict) and type(item.get("id")) is int:
            adapters[item["id"]] = {"id": item["id"], "path": item.get("path"),
                                    "scale": item.get("scale")}
    return adapters


def check_isolation(outputs, args):
    """Only checks user-defined differential sentinels and A1 == A2."""
    a1, b, a2 = outputs
    a = args.expect_a.casefold()
    other = args.expect_b.casefold()
    comparisons = {
        "a1_expected_only": a in a1.casefold() and other not in a1.casefold(),
        "b_expected_only": other in b.casefold() and a not in b.casefold(),
        "a2_expected_only": a in a2.casefold() and other not in a2.casefold(),
        "a_reproducible_exact": a1 == a2,
        "a_b_different": a1 != b,
    }
    return comparisons, all(comparisons.values())


def run_probe(args, record):
    parts = urlsplit(args.url)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1")
            or parts.path not in ("", "/") or parts.username or parts.password
            or parts.query or parts.fragment or parts.port is None):
        raise ValueError("--url debe ser http://127.0.0.1:PUERTO o localhost/::1, sin ruta")
    base_url = args.url.rstrip("/")
    opener = build_opener(ProxyHandler({}))  # Sin proxy/servicios remotos.
    health = fetch_json(opener, base_url + "/health", args.timeout)
    record["server"]["health"] = health
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RuntimeError("llama-server no está ready: " + repr(health))
    models = fetch_json(opener, base_url + "/v1/models", args.timeout)
    if not isinstance(models, dict) or not isinstance(models.get("data"), list):
        raise RuntimeError("/v1/models devolvió esquema incompatible")
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

    isolation = args.isolation_a is not None
    if isolation:
        adapters = available_adapters(opener, base_url, args.timeout)
        record["isolation"]["loaded_adapters"] = list(adapters.values())
        if args.isolation_a not in adapters or args.isolation_b not in adapters:
            raise RuntimeError("IDs LoRA A/B no aparecen en GET /lora-adapters")

    monitor = RSSMonitor(args.pid, args.rss_interval, args.test_harness) if args.pid else None
    if monitor:
        monitor.start()
    try:
        if isolation:
            outputs = []
            for tag, adapter_id in (("A1", args.isolation_a), ("B", args.isolation_b), ("A2", args.isolation_a)):
                measurement, visible = stream_completion(
                    opener, base_url, model_id, args, args.isolation_prompt, adapter_id,
                )
                record["isolation"]["steps"].append(
                    {"step": tag, "adapter_id": adapter_id, "measurement": measurement})
                outputs.append(visible)
            assertions, passed = check_isolation(outputs, args)
            record["isolation"]["assertions"] = assertions
            if not passed:
                raise RuntimeError("A/B/A no satisface las sentinelas o A1 != A2")
            record["status"] = "PASS_ABA_SENTINELS_ONLY"
        else:
            measurement, _ = stream_completion(
                opener, base_url, model_id, args, PROMPT, args.lora_id,
            )
            record["measurement"] = measurement
            record["status"] = "PASS_HTTP_SMOKE_ONLY"
    finally:
        if monitor:
            record["memory"] = monitor.finish()
            if record["memory"]["errors"]:
                raise RuntimeError("RSS incompleto: " + str(record["memory"]["errors"]))


def main():
    parser = argparse.ArgumentParser(description="Smoke real de llama-server local, sin modelos ni descargas")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", help="ruta JSON; por defecto reports/phase0 con nombre único")
    parser.add_argument("--expected-model", help="ID EXACTO de /v1/models; rechaza otro modelo")
    parser.add_argument("--lora-id", type=int, help="ID de adaptador cargado; solo selección por petición")
    parser.add_argument("--pid", type=int, help="PID real de llama-server para muestrear RSS Mac/Linux")
    parser.add_argument("--rss-interval", type=float, default=0.1, help="segundos entre muestras RSS (0.02–2)")
    parser.add_argument("--isolation-a", type=int, help="ID LoRA A cargado para secuencia A/B/A")
    parser.add_argument("--isolation-b", type=int, help="ID LoRA B cargado para secuencia A/B/A")
    parser.add_argument("--isolation-prompt", help="prompt idéntico que distingue respuestas entrenadas A/B")
    parser.add_argument("--expect-a", help="sentinela textual esperada SOLO con LoRA A")
    parser.add_argument("--expect-b", help="sentinela textual esperada SOLO con LoRA B")
    parser.add_argument("--test-harness", action="store_true",
                        help="USO EXCLUSIVO TEST: marca fake y prohíbe guardar en reports")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if (args.max_tokens < 1 or not 0 < args.timeout <= 300
            or not 0.02 <= args.rss_interval <= 2.0
            or any(x is not None and x < 0 for x in (args.lora_id, args.isolation_a, args.isolation_b))):
        parser.error("max-tokens > 0, timeout (0, 300], intervalo RSS [0.02, 2], IDs LoRA >= 0")
    isolation_fields = (args.isolation_a, args.isolation_b,
                        args.isolation_prompt, args.expect_a, args.expect_b)
    if any(x is not None for x in isolation_fields):
        if any(x is None for x in isolation_fields):
            parser.error("A/B/A requiere --isolation-a, --isolation-b, --isolation-prompt, --expect-a, --expect-b")
        if args.isolation_a == args.isolation_b or args.expect_a.casefold() == args.expect_b.casefold():
            parser.error("A y B deben ser IDs y sentinelas distintos")
        if not all(x.strip() for x in (args.isolation_prompt, args.expect_a, args.expect_b)):
            parser.error("prompt y sentinelas no pueden estar vacíos")
        if args.lora_id is not None:
            parser.error("usar A/B/A o --lora-id, no ambos")
    if args.pid is not None and args.pid <= 0:
        parser.error("--pid debe ser positivo")

    now = datetime.now(timezone.utc)
    output = Path(args.output) if args.output else ROOT / "reports" / "phase0" / ("http-smoke-" + now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(os.getpid()) + ".json")
    if args.test_harness:
        if not args.output:
            parser.error("--test-harness exige --output explícito en directorio temporal de tests")
        if output.resolve() == (ROOT / "reports").resolve() or (ROOT / "reports").resolve() in output.resolve().parents:
            parser.error("TEST fake no puede escribir bajo reports/")
    revision = git_value("rev-parse", "--verify", "HEAD")
    dirty = git_value("status", "--porcelain")
    record = {
        "schema": "spike.phase0.http-smoke.v2",
        "evidence_kind": "TEST_FAKE_HARNESS_NOT_BENCHMARK" if args.test_harness else "LIVE_SERVER_UNVERIFIED_MODEL",
        "status": "TEST_FAKE_FAIL" if args.test_harness else "FAIL",
        "timestamp_utc": now.isoformat(),
        "git_commit": revision,
        "git_dirty": bool(dirty) if dirty is not None else None,
        "client": {"os": platform.platform(), "architecture": platform.machine(),
                   "logical_cpus": os.cpu_count(), "ram_bytes": host_ram_bytes()},
        "server": {"url": args.url, "health": None, "model_id": None},
        "request": {"prompt": PROMPT, "max_tokens": args.max_tokens,
                    "seed": 42, "temperature": 0, "cache_prompt": False,
                    "requested_lora_id": args.lora_id},
        "measurement": empty_measurement(),
        "memory": None,
        "isolation": {"a_id": args.isolation_a, "b_id": args.isolation_b,
                      "prompt": args.isolation_prompt,
                      "expect_a": args.expect_a, "expect_b": args.expect_b,
                      "loaded_adapters": None, "steps": [], "assertions": None}
                     if args.isolation_a is not None else None,
        "error": None,
    }
    try:
        run_probe(args, record)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["status"] = "TEST_FAKE_FAIL" if args.test_harness else "FAIL"
    else:
        if args.test_harness:
            record["status"] = "TEST_FAKE_" + record["status"]

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
    return 0 if record["status"] in (
        "PASS_HTTP_SMOKE_ONLY", "PASS_ABA_SENTINELS_ONLY",
        "TEST_FAKE_PASS_HTTP_SMOKE_ONLY", "TEST_FAKE_PASS_ABA_SENTINELS_ONLY",
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
