#!/usr/bin/env python3
"""CPU-only benchmark on EXISTING local GGUF files; no downloads or installs.

Starts one local llama-server, runs real SSE requests, reports RSS/TTFT,
then always stops only its own child. Local execution is not a 16GB gate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.request import build_opener, ProxyHandler

from http_probe import git_value, host_ram_bytes, fetch_json, stream_completion
from rss_monitor import RSSMonitor

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = (
    "Reply with exactly one word: READY",
    "What is 17 multiplied by 23? Give only the integer.",
    "In one sentence, explain what an offline local language model is.",
    "Return a JSON object containing a boolean key called success and set it to true.",
    "Translate to Catalan: Good morning, how can I help you?",
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def port_available():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run(args, record):
    model = args.model.resolve()
    if model.is_symlink() or not model.is_file() or model.suffix != ".gguf":
        raise ValueError("Se exige archivo GGUF local regular (no enlaces simbólicos)")
    if model.stat().st_size < 1024:
        raise ValueError("Archivo GGUF inválido/demasiado pequeño")
    model_hash = sha256(model)
    record["model"] = {"path": str(model), "sha256": model_hash,
                       "size_bytes": model.stat().st_size,
                       "upstream_repository": args.upstream_repository,
                       "revision": args.upstream_revision}
    if model_hash != args.sha256:
        raise ValueError(f"Hash GGUF no coincide: encontrado {model_hash}, esperado {args.sha256}")
    executable = shutil.which("llama-server")
    if not executable:
        raise RuntimeError("llama-server no existe en PATH")
    record["llama_server"] = {"path": executable,
                              "version": subprocess.check_output(
                                  [executable, "--version"], text=True,
                                  stderr=subprocess.STDOUT, timeout=10).strip()[:500]}
    port = port_available()
    base = f"http://127.0.0.1:{port}"
    command = [
        executable, "--model", str(model), "--host", "127.0.0.1",
        "--port", str(port), "--n-gpu-layers", "0",
        "--no-mmproj", "--ctx-size", str(args.context),
        "--parallel", "1", "--threads", str(args.threads),
        "--no-webui", "--cache-ram", "0",
        "--reasoning", args.reasoning,
    ]
    if args.disable_fit:
        command.extend(["--fit", "off"])
    if args.draft:
        draft = args.draft.resolve()
        if not draft.is_file() or draft.is_symlink() or draft.suffix != ".gguf":
            raise ValueError("Draft GGUF local ausente o no regular")
        draft_hash = sha256(draft)
        if draft_hash != args.draft_sha256:
            raise ValueError("Hash de modelo draft no coincide")
        command.extend(["--spec-draft-model", str(draft), "--spec-draft-ngl", "0"])
        record["draft"] = {"path": str(draft), "sha256": draft_hash, "size_bytes": draft.stat().st_size}
    record["command_redacted"] = command
    record["cpu_only_configured"] = True
    record["model_cpu16_verified"] = False
    record["runtime_start_ms"] = None
    opener = build_opener(ProxyHandler({}))
    proc = None
    monitor = None
    result_rows = []
    log_path = Path(args.output).with_suffix(".llama.log")
    try:
        with log_path.open("x", encoding="utf-8") as log:
            started_at = time.perf_counter()
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
            record["server_pid"] = proc.pid
            monitor = RSSMonitor(proc.pid, interval=0.1)
            monitor.start()
            while time.perf_counter() - started_at <= args.startup_timeout:
                if proc.poll() is not None:
                    raise RuntimeError(f"llama-server salió con código {proc.returncode}; revisar {log_path}")
                try:
                    health = fetch_json(opener, base + "/health", 3)
                    if isinstance(health, dict) and health.get("status") == "ok":
                        break
                except (URLError, HTTPError, ValueError, TimeoutError):
                    pass
                time.sleep(0.3)
            else:
                raise TimeoutError(f"llama-server no listo en {args.startup_timeout}s")
            record["runtime_start_ms"] = round(1000 * (time.perf_counter() - started_at), 3)
            models = fetch_json(opener, base + "/v1/models", 5)
            all_models = models.get("data") if isinstance(models, dict) else None
            if not isinstance(all_models, list) or len(all_models) != 1 or not all_models[0].get("id"):
                raise RuntimeError("ID modelo no encontrado o ambiguo")
            model_id = all_models[0]["id"]
            record["served_model_id"] = model_id
            from types import SimpleNamespace
            request_args = SimpleNamespace(timeout=args.timeout, max_tokens=args.max_tokens)
            for run_idx in range(args.runs):
                prompt = PROMPTS[run_idx % len(PROMPTS)]
                measure, response = stream_completion(opener, base, model_id, request_args, prompt)
                result_rows.append({"run": run_idx + 1, "prompt_id": run_idx % len(PROMPTS) + 1,
                                    "measurement": measure,
                                    "response_sha256": hashlib.sha256(response.encode()).hexdigest()})
            record["samples"] = result_rows
            record["ttft_ms_median"] = statistics.median(r["measurement"]["ttft_ms"] for r in result_rows)
            record["ttft_ms_max"] = max(r["measurement"]["ttft_ms"] for r in result_rows)
            record["total_ms_median"] = statistics.median(r["measurement"]["total_ms"] for r in result_rows)
            record["status"] = "OBSERVED_LOCAL_CPU_ONLY_NOT_16GB_GATE"
    finally:
        if monitor:
            record["memory"] = monitor.finish()
        stop_process(proc)
        if log_path.is_file():
            record["llama_log_path"] = str(log_path)
            # Never write full server logs inside JSON: may contain prompts.
            record["llama_log_size_bytes"] = log_path.stat().st_size


def main():
    parser = argparse.ArgumentParser(description="Bench REAL local GGUF in CPU-only llama-server, no downloads")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--upstream-repository", required=True)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--draft-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--context", type=int, default=2048)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--startup-timeout", type=int, default=120)
    parser.add_argument("--disable-fit", action="store_true", help="Desactivar auto ajuste llama.cpp (-fit off) para diagnóstico")
    parser.add_argument("--reasoning", choices=("on", "off"), default="off",
                        help="Fijar modo de razonamiento para comparar solicitudes; por defecto off")
    args = parser.parse_args()
    if (len(args.sha256) != 64 or any(c not in "0123456789abcdef" for c in args.sha256)
            or args.draft and not args.draft_sha256):
        parser.error("SHA-256 principal y draft (si aplica) obligatorios")
    if not (1 <= args.runs <= 30 and 256 <= args.context <= 16384
            and 1 <= args.threads <= 16 and 1 <= args.max_tokens <= 256
            and 5 <= args.timeout <= 300 and 10 <= args.startup_timeout <= 300):
        parser.error("Parámetros runs/ctx/threads/tokens/timeout fuera de límites")
    now = datetime.now(timezone.utc)
    output = args.output or ROOT / "reports" / "phase0" / (
        "cpu-bench-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    args.output = output
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "spike.phase0.local-cpu-bench.v1",
        "timestamp_utc": now.isoformat(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": bool(git_value("status", "--porcelain")),
        "hardware": {"os": platform.platform(), "architecture": platform.machine(),
                     "ram_bytes": host_ram_bytes(), "logical_cpus": os.cpu_count(),
                     "gpu_layers_requested": 0},
        "test_parameters": {"runs": args.runs, "ctx": args.context, "threads": args.threads,
                            "max_tokens": args.max_tokens, "disable_fit": args.disable_fit,
                            "reasoning": args.reasoning},
        "status": "FAIL", "f0_gate_passed": False,
        "samples": [], "memory": None, "error": None,
        "warnings": ["Mac 36GiB no acredita 16GB; RSS proceso no equivale a RAM total.",
                     "TTFT primera parte SSE; la velocidad tokens/s no se afirma sin contador preciso.",
                     "No es evaluación de calidad, comparativa Gemma ni gate de especialista."],
    }
    try:
        run(args, record)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        record["status"] = "FAIL"
        record["error"] = f"{type(exc).__name__}: {exc}"
    try:
        with output.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        parser.error(f"No se puede crear JSON: {exc}")
    print(record["status"], output)
    if record["error"]:
        print(record["error"], file=sys.stderr)
    return 0 if record["status"] == "OBSERVED_LOCAL_CPU_ONLY_NOT_16GB_GATE" else 1


if __name__ == "__main__":
    sys.exit(main())
