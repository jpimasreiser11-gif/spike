#!/usr/bin/env python3
"""S7 Phase 0 observations against ALREADY RUNNING local model servers.

No installers, model downloads, subprocess server startup or remote URLs.
All synthetic HTTP tests MUST set --test-harness and cannot write into reports/.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener

from http_probe import fetch_json, git_value, host_ram_bytes, stream_completion
from rss_monitor import RSSMonitor

ROOT = Path(__file__).resolve().parents[2]
MAX_DATASET_BYTES = 1_000_000


def local_base(url):
    """Strictly allow numeric loopback, avoiding DNS and proxy lookups."""
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.port is None or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("solo http://127.0.0.1:PUERTO o http://[::1]:PUERTO sin ruta")
    return url.rstrip("/")


def server_model(opener, url, timeout, requested_model):
    health = fetch_json(opener, url + "/health", timeout)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RuntimeError("endpoint no está ready: " + repr(health))
    models = fetch_json(opener, url + "/v1/models", timeout)
    if not isinstance(models, dict) or not isinstance(models.get("data"), list):
        raise RuntimeError("/v1/models inválido")
    ids = [d["id"] for d in models["data"] if isinstance(d, dict) and isinstance(d.get("id"), str)]
    if requested_model not in ids:
        raise RuntimeError(f"modelo {requested_model!r} no está en /v1/models: {ids!r}")
    return {"url": url, "model_id": requested_model, "health": health, "advertised_models": ids}


def process_evidence(pid, *, draft, test_harness):
    if pid is None:
        return None
    monitor = RSSMonitor(pid, test_fixture=test_harness)
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                      stderr=subprocess.DEVNULL, text=True, timeout=5).strip()
    if not command:
        raise RuntimeError("PID no existe o comando no accesible")
    if not test_harness:
        contains_draft = "--spec-draft-model" in command or "--model-draft" in command or " -md " in command
        if draft and not contains_draft:
            raise RuntimeError("PID draft no muestra --spec-draft-model; no está acreditado S7")
        if not draft and contains_draft:
            raise RuntimeError("PID baseline parece usar speculative decoding")
    return monitor, {"pid": pid, "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                     "draft_flag_visible": ("--spec-draft-model" in command or "--model-draft" in command),
                     "binding_to_http_endpoint_verified": False}


def embedding_cpu_evidence(pid, *, test_harness):
    monitor, record = process_evidence(pid, draft=False, test_harness=test_harness)
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                      stderr=subprocess.DEVNULL, text=True, timeout=5).strip()
    cpu_flag = any(text in command for text in (
        "--n-gpu-layers 0", "--gpu-layers 0", "-ngl 0",
        "--n-gpu-layers=0", "--gpu-layers=0", "-ngl=0",
    ))
    record["cpu_only_flag_visible"] = cpu_flag
    if not test_harness and not cpu_flag:
        raise RuntimeError("servidor embeddings sin evidencia CLI de GPU layers=0; CPU no acreditada")
    return monitor, record


def compare(args, record):
    baseline_url, draft_url = local_base(args.baseline_url), local_base(args.draft_url)
    if baseline_url == draft_url:
        raise ValueError("baseline y draft deben usar dos puertos/servidores distintos")
    opener = build_opener(ProxyHandler({}))
    record["servers"] = {"baseline": server_model(opener, baseline_url, args.timeout, args.model_id),
                         "draft": server_model(opener, draft_url, args.timeout, args.model_id)}
    monitors = {}
    for label, pid, draft_mode in (("baseline", args.baseline_pid, False),
                                   ("draft", args.draft_pid, True)):
        if pid is None:
            record["process_evidence"][label] = None
            continue
        monitor, metadata = process_evidence(pid, draft=draft_mode, test_harness=args.test_harness)
        monitors[label] = monitor
        record["process_evidence"][label] = metadata
    if args.baseline_pid is not None and args.baseline_pid == args.draft_pid:
        raise ValueError("baseline/draft no pueden apuntar al mismo PID")

    request = SimpleNamespace(timeout=args.timeout, max_tokens=args.max_tokens)
    started_monitors = []
    try:
        for monitor in monitors.values():
            monitor.start()
            started_monitors.append(monitor)
        for round_id in range(args.rounds):
            # Alternating order reduces simple time-order bias; no claim of causality.
            order = ("baseline", "draft") if round_id % 2 == 0 else ("draft", "baseline")
            for label in order:
                base = baseline_url if label == "baseline" else draft_url
                measurement, content = stream_completion(
                    opener, base, args.model_id, request, args.prompt)
                record["samples"].append({"round": round_id + 1, "arm": label,
                                          "measurement": measurement,
                                          "response_sha256": hashlib.sha256(content.encode()).hexdigest()})
    finally:
        for label, monitor in monitors.items():
            if monitor in started_monitors:
                memory = monitor.finish()
                record["process_evidence"][label]["memory"] = memory
                if memory["errors"]:
                    raise RuntimeError("falló RSS de " + label + ": " + repr(memory["errors"]))

    summary = {}
    paired_hash_checks = []
    for round_id in range(1, args.rounds + 1):
        paired = {s["arm"]: s["response_sha256"] for s in record["samples"] if s["round"] == round_id}
        if len(paired) != 2:
            raise RuntimeError("ronda incompleta: faltan baseline/draft")
        paired_hash_checks.append({"round": round_id, "visible_output_equal": paired["baseline"] == paired["draft"]})
    for label in ("baseline", "draft"):
        rows = [s["measurement"] for s in record["samples"] if s["arm"] == label]
        if len(rows) != args.rounds or any(m["ttft_ms"] is None for m in rows):
            raise RuntimeError("faltan muestras reales de " + label)
        summary[label] = {
            "n": len(rows),
            "median_ttft_ms": statistics.median(m["ttft_ms"] for m in rows),
            "median_total_ms": statistics.median(m["total_ms"] for m in rows),
        }
    baseline_total, draft_total = summary["baseline"]["median_total_ms"], summary["draft"]["median_total_ms"]
    summary["observed_total_ratio_baseline_over_draft"] = (
        round(baseline_total / draft_total, 5) if draft_total > 0 else None)
    summary["paired_visible_output_checks"] = paired_hash_checks
    summary["all_visible_outputs_equal"] = all(x["visible_output_equal"] for x in paired_hash_checks)
    summary["proof_of_acceleration"] = False
    summary["caution"] = "Observational small-sample comparison; no causal acceleration claim. " \
                         "Server PID not authenticated to port, nor draft identity verified by HTTP."
    record["summary"] = summary
    if not summary["all_visible_outputs_equal"]:
        raise RuntimeError("baseline/draft generaron respuestas visibles diferentes; tiempos no comparables")
    record["status"] = "OBSERVED_PAIR_NOT_CERTIFIED"


def validate_dataset(source):
    if (not isinstance(source, dict) or source.get("license_review") != "approved"
            or source.get("held_out") is not True or not isinstance(source.get("examples"), list)):
        raise ValueError("dataset debe declarar license_review=approved, held_out=true y examples[]")
    examples = source["examples"]
    if len(examples) < 6 or len(examples) > 500:
        raise ValueError("dataset requiere entre 6 y 500 ejemplos")
    ids, texts, count = set(), set(), {}
    for row in examples:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                                            for k in ("id", "text", "label", "split")):
            raise ValueError("cada ejemplo necesita id/text/label/split no vacíos")
        if row["split"] not in ("train", "test") or len(row["text"]) > 4000:
            raise ValueError("split inválido o texto >4000 caracteres")
        if row["id"] in ids or row["text"].strip().casefold() in texts:
            raise ValueError("IDs o textos duplicados: contaminación train/test")
        ids.add(row["id"])
        texts.add(row["text"].strip().casefold())
        key = (row["label"], row["split"])
        count[key] = count.get(key, 0) + 1
    labels = sorted(set(label for label, _ in count))
    if len(labels) < 2:
        raise ValueError("routing requiere al menos dos etiquetas distintas")
    for label in labels:
        if count.get((label, "train"), 0) < 2 or count.get((label, "test"), 0) < 1:
            raise ValueError("cada etiqueta exige >=2 train y >=1 test")
    return examples, labels


def normalize(values):
    if not isinstance(values, list) or not values or len(values) > 100000:
        raise ValueError("vector embedding inválido")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        raise ValueError("embedding debe contener solo números finitos")
    norm = math.sqrt(sum(x * x for x in values))
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("vector embedding nulo/no finito")
    return [x / norm for x in values]


def embedding(opener, url, model_id, sentence, timeout):
    payload = json.dumps({"model": model_id, "input": sentence}).encode()
    request = Request(url + "/v1/embeddings", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("respuesta embeddings demasiado grande")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list) or len(parsed["data"]) != 1:
        raise ValueError("/v1/embeddings: esquema inválido o número de vectores inesperado")
    vector = parsed["data"][0]
    if not isinstance(vector, dict) or "embedding" not in vector:
        raise ValueError("/v1/embeddings no devolvió vector")
    return normalize(vector["embedding"]), round((time.perf_counter() - started) * 1000, 3)


def route(args, record):
    url = local_base(args.endpoint)
    dataset_path = Path(args.dataset)
    if not dataset_path.is_file() or dataset_path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("--dataset no existe o supera 1 MB")
    raw = dataset_path.read_bytes()
    source = json.loads(raw)
    rows, labels = validate_dataset(source)
    record["dataset"] = {"sha256": hashlib.sha256(raw).hexdigest(), "path": str(dataset_path.resolve()),
                         "n": len(rows), "labels": labels, "license_review": "approved", "held_out": True}
    opener = build_opener(ProxyHandler({}))
    record["server"] = server_model(opener, url, args.timeout, args.model_id)
    monitor = None
    if args.embedding_pid is not None:
        monitor, record["embedding_process_evidence"] = embedding_cpu_evidence(
            args.embedding_pid, test_harness=args.test_harness)
    samples, dimension = [], None
    try:
        if monitor:
            monitor.start()
        for row in rows:
            vector, elapsed = embedding(opener, url, args.model_id, row["text"], args.timeout)
            if dimension is None:
                dimension = len(vector)
            if len(vector) != dimension:
                raise RuntimeError("dimensión de embedding cambió durante evaluación")
            samples.append({"id": row["id"], "label": row["label"], "split": row["split"],
                            "vector": vector, "request_ms": elapsed})
    finally:
        if monitor and monitor._thread is not None:
            memory = monitor.finish()
            record["embedding_process_evidence"]["memory"] = memory
            if memory["errors"]:
                raise RuntimeError("RSS embeddings incompleto: " + repr(memory["errors"]))
    # Centroids from labeled TRAIN examples only, normalized for cosine similarity.
    centroids = {}
    for label in labels:
        train = [s["vector"] for s in samples if s["label"] == label and s["split"] == "train"]
        centroids[label] = normalize([sum(vector[j] for vector in train) / len(train)
                                      for j in range(dimension)])
    predictions = []
    for row in samples:
        if row["split"] != "test":
            continue
        scores = {label: sum(a * b for a, b in zip(row["vector"], centroid))
                  for label, centroid in centroids.items()}
        predicted = sorted(labels, key=lambda label: (-scores[label], label))[0]
        predictions.append({"id": row["id"], "actual": row["label"], "predicted": predicted,
                            "correct": predicted == row["label"],
                            "scores": {key: round(value, 7) for key, value in scores.items()}})
    record["result"] = {
        "routing_method": "cosine nearest normalized train centroid (text embedding endpoint)",
        "embedding_dimensions": dimension,
        "n_train": sum(r["split"] == "train" for r in rows),
        "n_test": len(predictions),
        "accuracy": sum(p["correct"] for p in predictions) / len(predictions),
        "macro_recall": sum(sum(p["correct"] for p in predictions if p["actual"] == label) /
                            sum(p["actual"] == label for p in predictions) for label in labels) / len(labels),
        "request_ms_median": statistics.median(s["request_ms"] for s in samples),
        "predictions": predictions,
        "cpu_execution_verified": False,
        "limitations": "Held-out by label but independence/provenance not automatically proved; "
                       "small dataset and local HTTP timing are not proof of 16GB CPU routing accuracy.",
    }
    record["status"] = "OBSERVED_EMBEDDING_ROUTING_NOT_CERTIFIED"


def main(argv=None):
    parser = argparse.ArgumentParser(description="S7 read-only checks: speculative vs baseline and embedding routing")
    parser.add_argument("--output", help="JSON path; exclusive create, no overwrite")
    parser.add_argument("--test-harness", action="store_true", help="TEST fake only; never writes reports/")
    parser.add_argument("--timeout", type=float, default=30)
    subparsers = parser.add_subparsers(dest="action", required=True)
    c = subparsers.add_parser("compare", help="two already-running local servers")
    c.add_argument("--baseline-url", required=True)
    c.add_argument("--draft-url", required=True)
    c.add_argument("--model-id", required=True, help="same primary model ID advertised on both servers")
    c.add_argument("--baseline-pid", type=int)
    c.add_argument("--draft-pid", type=int)
    c.add_argument("--rounds", type=int, default=4)
    c.add_argument("--max-tokens", type=int, default=64)
    c.add_argument("--prompt", default="Explain in two sentences why reproducibility matters.")
    e = subparsers.add_parser("route", help="evaluate labeled train/test dataset on running embeddings endpoint")
    e.add_argument("--endpoint", required=True)
    e.add_argument("--model-id", required=True)
    e.add_argument("--dataset", required=True)
    e.add_argument("--embedding-pid", type=int, help="PID del servidor local para RSS y flag --n-gpu-layers 0")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 300:
        parser.error("--timeout debe estar entre 0 y 300 segundos")
    if args.action == "compare" and (not 2 <= args.rounds <= 40 or not 1 <= args.max_tokens <= 2048
                                      or not args.prompt.strip()):
        parser.error("compare requiere rounds [2, 40], max-tokens [1, 2048], prompt no vacío")
    if (args.action == "compare" and
            any(pid is not None and pid <= 0 for pid in (args.baseline_pid, args.draft_pid))) or (
            args.action == "route" and args.embedding_pid is not None and args.embedding_pid <= 0):
        parser.error("PID debe ser entero positivo")
    now = datetime.now(timezone.utc)
    default = ROOT / "reports" / "phase0" / (f"s7-{args.action}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{os.getpid()}.json")
    output = Path(args.output) if args.output else default
    if args.test_harness:
        if (args.output is None or output.resolve() == (ROOT / "reports").resolve()
                or (ROOT / "reports").resolve() in output.resolve().parents):
            parser.error("TEST exige --output externo a reports/; fake nunca benchmark")
    record = {"schema": "spike.phase0.s7-readiness.v1",
              "evidence_kind": "TEST_FAKE_NOT_BENCHMARK" if args.test_harness else "LOCAL_HTTP_OBSERVATION",
              "status": "TEST_FAKE_FAIL" if args.test_harness else "FAIL",
              "timestamp_utc": now.isoformat(), "git_commit": git_value("rev-parse", "--verify", "HEAD"),
              "git_dirty": bool(git_value("status", "--porcelain")),
              "host": {"os": platform.platform(), "architecture": platform.machine(),
                       "ram_bytes": host_ram_bytes(), "logical_cpus": os.cpu_count()},
              "action": args.action, "server": None, "servers": None,
              "process_evidence": {"baseline": None, "draft": None},
              "embedding_process_evidence": None,
              "samples": [], "summary": None, "dataset": None, "result": None, "error": None}
    try:
        if args.action == "compare":
            compare(args, record)
        else:
            route(args, record)
        if args.test_harness:
            record["status"] = "TEST_FAKE_" + record["status"]
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        record["status"] = "TEST_FAKE_FAIL" if args.test_harness else "FAIL"
        record["error"] = f"{type(exc).__name__}: {exc}"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        print("FAIL: cannot exclusively write JSON: " + str(exc), file=sys.stderr)
        return 1
    print(f"{record['status']}: {output}")
    if record["error"]:
        print(record["error"], file=sys.stderr)
    return 1 if record["error"] is not None else 0


if __name__ == "__main__":
    sys.exit(main())
