#!/usr/bin/env python3
"""Smoke HTTP real y TTFT SSE para llama-server existente. Solo stdlib."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
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
            "visible_response_sha256": None, "reasoning_sha256": None,
            "completion_tokens_reported": None, "completion_tokens_source": None,
            "end_to_end_completion_tokens_per_second": None}


def stream_completion(opener, base_url, model_id, args, prompt, lora_id=None, *, explicit_base=False):
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "seed": 42, "max_tokens": args.max_tokens,
        "stream": True, "cache_prompt": False,
        "stream_options": {"include_usage": True},
    }
    if explicit_base:
        if lora_id is not None:
            raise ValueError("explicit_base no admite adaptador")
        payload["lora"] = []
    elif lora_id is not None:
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
            usage = event.get("usage")
            if usage is not None:
                if not isinstance(usage, dict):
                    raise RuntimeError("usage SSE no es objeto")
                completion_tokens = usage.get("completion_tokens")
                if completion_tokens is not None:
                    if type(completion_tokens) is not int or completion_tokens < 0:
                        raise RuntimeError("usage.completion_tokens inválido")
                    previous = measure["completion_tokens_reported"]
                    if previous is not None and previous != completion_tokens:
                        raise RuntimeError("usage.completion_tokens contradictorio")
                    measure["completion_tokens_reported"] = completion_tokens
                    measure["completion_tokens_source"] = "server_sse_usage"
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
    if measure["completion_tokens_reported"] is not None and measure["total_ms"] > 0:
        measure["end_to_end_completion_tokens_per_second"] = round(
            measure["completion_tokens_reported"] * 1000 / measure["total_ms"], 4)
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


def check_s2_content(text, role, expected):
    """One role sentinel, and neither of the other two, must be present."""
    folded = text.casefold()
    required = expected[role].casefold()
    forbidden = [value.casefold() for name, value in expected.items() if name != role]
    return required in folded and all(value not in folded for value in forbidden)


def measure_s2(args, record, opener, base_url, model_id):
    """Repeated real per-request LoRA observations; never a direct adapter switch timer."""
    other_parts = urlsplit(args.s2_isolated_url)
    if (other_parts.scheme != "http" or other_parts.hostname not in ("127.0.0.1", "localhost", "::1")
            or other_parts.port is None or other_parts.path not in ("", "/")
            or other_parts.username or other_parts.password or other_parts.query or other_parts.fragment):
        raise ValueError("S2 isolated URL debe ser un servidor HTTP loopback sin ruta")
    isolated_url = args.s2_isolated_url.rstrip("/")
    if isolated_url == base_url:
        raise ValueError("S2 requiere dos URLs de servidor distintas")
    # For LIVE evidence two distinct existing OS processes are mandatory.
    if not args.test_harness and (args.pid is None or args.s2_isolated_pid is None):
        raise RuntimeError("S2 real exige --pid y --s2-isolated-pid de procesos llama-server distintos")
    if args.pid is not None and args.pid == args.s2_isolated_pid and not args.test_harness:
        raise RuntimeError("S2 real no permite usar el mismo PID para ambos servidores")

    isolated_health = fetch_json(opener, isolated_url + "/health", args.timeout)
    if not isinstance(isolated_health, dict) or isolated_health.get("status") != "ok":
        raise RuntimeError("servidor base aislado no está listo")
    isolated_models = fetch_json(opener, isolated_url + "/v1/models", args.timeout)
    if (not isinstance(isolated_models, dict)
            or not isinstance(isolated_models.get("data"), list)
            or model_id not in [m.get("id") for m in isolated_models["data"] if isinstance(m, dict)]):
        raise RuntimeError("servidor base aislado no ofrece exactamente el mismo ID del modelo principal")

    adapters = available_adapters(opener, base_url, args.timeout)
    if not adapters or args.s2_a not in adapters or args.s2_b not in adapters:
        raise RuntimeError("S2 requiere ambos adaptadores reales A/B en GET /lora-adapters")
    isolated_adapters = available_adapters(opener, isolated_url, args.timeout)
    if isolated_adapters:
        raise RuntimeError("servidor base aislado anuncia LoRAs; baseline no aislado")
    record["s2"]["adapters"] = [adapters[args.s2_a], adapters[args.s2_b]]
    record["s2"]["isolated_server"] = {
        "url": isolated_url, "model_id": model_id, "health": isolated_health,
        "adapters_reported": [], "pid": args.s2_isolated_pid,
        "pid_to_http_port_binding_verified": False,
    }
    record["s2"]["main_process_pid"] = args.pid
    record["s2"]["process_pids_distinct"] = (
        args.pid is not None and args.s2_isolated_pid is not None and args.pid != args.s2_isolated_pid)
    # A different PID is useful evidence but OS PID->port mapping is not authenticated.
    primary_monitor = RSSMonitor(args.pid, args.rss_interval, args.test_harness) if args.pid else None
    isolated_monitor = RSSMonitor(args.s2_isolated_pid, args.rss_interval, args.test_harness) if args.s2_isolated_pid else None
    monitors = {"main": primary_monitor, "isolated": isolated_monitor}
    started = []
    roles = {
        "A": {"url": base_url, "id": args.s2_a, "explicit_base": False},
        "B": {"url": base_url, "id": args.s2_b, "explicit_base": False},
        "base": {"url": base_url, "id": None, "explicit_base": True},
        "isolated_base": {"url": isolated_url, "id": None, "explicit_base": True},
    }
    expected = {"A": args.s2_expect_a, "B": args.s2_expect_b, "base": args.s2_expect_base}
    record["s2"]["protocol"] = {
        "cycles": args.s2_rounds, "switches_per_cycle": 4,
        "observed_switch_transitions": args.s2_rounds * 4,
        "sequence_per_cycle": ["isolated_base", "A1", "B", "A2", "base1", "A", "base2"],
        "seed": 42, "temperature": 0, "cache_prompt": False,
        "base_request_lora": [],
        "max_tokens": args.max_tokens,
        "prompt": args.s2_prompt,
    }
    reference_outputs = {}
    try:
        for monitor in monitors.values():
            if monitor:
                monitor.start()
                started.append(monitor)
        for cycle in range(1, args.s2_rounds + 1):
            outcomes = {}
            for tag, role in (("isolated_base", "isolated_base"), ("A1", "A"), ("B", "B"),
                              ("A2", "A"), ("base1", "base"), ("A", "A"), ("base2", "base")):
                config = roles[role]
                measurement, visible = stream_completion(
                    opener, config["url"], model_id, args, args.s2_prompt,
                    config["id"], explicit_base=config["explicit_base"])
                required = "base" if role == "isolated_base" else role
                correct = check_s2_content(visible, required, expected)
                sample = {
                    "cycle": cycle, "step": tag, "role": required,
                    "source": "isolated" if role == "isolated_base" else "multi_lora",
                    "requested_adapter_id": config["id"],
                    "base_lora_explicitly_empty": config["explicit_base"],
                    "expected_role_sentinel_exclusive": correct,
                    "measurement": measurement,
                }
                record["s2"]["samples"].append(sample)
                outcomes[tag] = (visible, correct)
                if not correct:
                    raise RuntimeError(f"S2 contaminación/sentinela no confirmada: ronda={cycle} paso={tag}")
                if tag in reference_outputs and reference_outputs[tag] != visible:
                    raise RuntimeError(f"S2 salida no reproducible entre rondas: paso={tag}, ronda={cycle}")
                reference_outputs.setdefault(tag, visible)
            match_checks = {
                "aba_a1_equals_a2": outcomes["A1"][0] == outcomes["A2"][0],
                "base_a_base_equals": outcomes["base1"][0] == outcomes["base2"][0],
                "base_matches_isolated": outcomes["base1"][0] == outcomes["isolated_base"][0],
            }
            record["s2"]["cycles"].append({"cycle": cycle, "assertions": match_checks})
            if not all(match_checks.values()):
                raise RuntimeError(f"S2 discrepancia A/B/A o base/A/base: ronda={cycle}")
            cycle_steps = {s["step"]: s for s in record["s2"]["samples"][-7:]}
            for previous_step, next_step, transition_name in (
                    ("A1", "B", "A->B"), ("B", "A2", "B->A"),
                    ("base1", "A", "base->A"), ("A", "base2", "A->base")):
                observed = cycle_steps[next_step]["measurement"]
                record["s2"]["transitions"].append({
                    "cycle": cycle, "from": previous_step, "to": next_step,
                    "transition": transition_name,
                    "client_ttft_proxy_ms": observed["ttft_ms"],
                    "client_total_response_ms": observed["total_ms"],
                    "true_adapter_activation_ms": None,
                    "independent_switch_ack_received": False,
                })
    finally:
        for name, monitor in monitors.items():
            if monitor in started:
                memory = monitor.finish()
                record["s2"]["memory"][name] = memory
                if memory["errors"]:
                    raise RuntimeError("S2 RSS incompleto " + name + ": " + repr(memory["errors"]))

    summary = {}
    for role in ("A", "B", "base", "isolated_base"):
        measurements = [s["measurement"] for s in record["s2"]["samples"] if
                        (s["source"] == "isolated" if role == "isolated_base" else
                         s["source"] == "multi_lora" and s["role"] == role)]
        if not measurements:
            raise RuntimeError("S2 sin mediciones para rol " + role)
        summary[role] = {
            "samples": len(measurements),
            "median_ttft_ms": statistics.median(m["ttft_ms"] for m in measurements),
            "p95_ttft_ms": sorted(m["ttft_ms"] for m in measurements)[
                min(len(measurements) - 1, int((len(measurements) - 1) * 0.95 + 0.999999))],
            "median_total_ms": statistics.median(m["total_ms"] for m in measurements),
        }
    for entry in record["s2"]["cycles"]:
        if not all(entry["assertions"].values()):
            raise RuntimeError("S2 ciclo A/B/A inconsistente")
    proxy_differences = [
        s["measurement"]["ttft_ms"] - summary["isolated_base"]["median_ttft_ms"]
        for s in record["s2"]["samples"] if s["step"] in ("A1", "B", "A2", "A")
    ]
    transition_summary = {}
    for transition_name in ("A->B", "B->A", "base->A", "A->base"):
        observations = [s["client_ttft_proxy_ms"] for s in record["s2"]["transitions"]
                        if s["transition"] == transition_name]
        if len(observations) != args.s2_rounds:
            raise RuntimeError("S2 no registró todas las transiciones " + transition_name)
        transition_summary[transition_name] = {
            "n": len(observations),
            "median_client_ttft_proxy_ms": statistics.median(observations),
            "max_client_ttft_proxy_ms": max(observations),
        }
    if len(record["s2"]["transitions"]) != args.s2_rounds * 4:
        raise RuntimeError("S2 conteo de transiciones incorrecto")
    record["s2"]["summary"] = {
        "by_role": summary,
        "by_transition": transition_summary,
        "switch_proxy_name": "client_ttft_minus_isolated_base_median_ms",
        "switch_proxy_observed_median_ms": statistics.median(proxy_differences),
        "switch_proxy_observed_max_ms": max(proxy_differences),
        "switch_ack_ms": None,
        "switch_gate_500ms": "NOT_VERIFIABLE_NO_INDEPENDENT_ADAPTER_SWITCH_ACK",
        "isolation_gate": "SENTINEL_ONLY_NOT_CERTIFIED",
        "api_limits": "Client TTFT includes HTTP, queue, tokenization/prefill/inference; "
                      "no direct measurement of LoRA activation/ack. "
                      "Distinct local PIDs do not prove port ownership.",
    }
    record["status"] = "OBSERVED_S2_PROXY_ONLY"


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
    if args.s2_a is not None:
        return measure_s2(args, record, opener, base_url, model_id)
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
    parser.add_argument("--s2-a", type=int, help="S2: ID del adaptador A ya cargado")
    parser.add_argument("--s2-b", type=int, help="S2: ID del adaptador B ya cargado")
    parser.add_argument("--s2-isolated-url", help="S2: segundo llama-server local sin LoRA")
    parser.add_argument("--s2-isolated-pid", type=int, help="S2: PID del proceso base aislado")
    parser.add_argument("--s2-rounds", type=int, default=30,
                        help="S2: al menos 30 ciclos completos por secuencia")
    parser.add_argument("--s2-prompt", help="S2: prompt igual para A/B/base")
    parser.add_argument("--s2-expect-a", help="S2: sentinela exclusiva de LoRA A")
    parser.add_argument("--s2-expect-b", help="S2: sentinela exclusiva de LoRA B")
    parser.add_argument("--s2-expect-base", help="S2: sentinela exclusiva de base")
    parser.add_argument("--test-harness", action="store_true",
                        help="USO EXCLUSIVO TEST: marca fake y prohíbe guardar en reports")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if (args.max_tokens < 1 or not 0 < args.timeout <= 300
            or not 0.02 <= args.rss_interval <= 2.0
            or any(x is not None and x < 0 for x in (
                args.lora_id, args.isolation_a, args.isolation_b, args.s2_a, args.s2_b))):
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
    s2_fields = (args.s2_a, args.s2_b, args.s2_isolated_url,
                 args.s2_prompt, args.s2_expect_a, args.s2_expect_b, args.s2_expect_base)
    if any(x is not None for x in s2_fields):
        if any(x is None for x in s2_fields):
            parser.error("S2 exige --s2-a/b, --s2-isolated-url, --s2-prompt, "
                         "--s2-expect-a/b/base")
        if args.s2_a == args.s2_b or not 30 <= args.s2_rounds <= 200:
            parser.error("S2 exige adaptadores distintos y al menos 30 rondas (máximo 200)")
        if (any(not x.strip() for x in (
                args.s2_prompt, args.s2_expect_a, args.s2_expect_b, args.s2_expect_base))
                or len({args.s2_expect_a.casefold(), args.s2_expect_b.casefold(),
                        args.s2_expect_base.casefold()}) != 3):
            parser.error("S2 exige prompt y tres sentinelas no vacías y diferentes")
        if (args.lora_id is not None or any(x is not None for x in isolation_fields)):
            parser.error("S2 es incompatible con --lora-id y con --isolation-*")
    elif args.s2_isolated_pid is not None:
        parser.error("--s2-isolated-pid solo tiene sentido en modo S2")
    if args.s2_isolated_pid is not None and args.s2_isolated_pid <= 0:
        parser.error("--s2-isolated-pid debe ser positivo")

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
        "schema": "spike.phase0.http-smoke.v3" if args.s2_a is not None else "spike.phase0.http-smoke.v2",
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
        "s2": ({
            "gate_type": "S2_MULTI_LORA_SWITCH_TIMING_PROXY",
            "model_id": None,
            "adapters": None,
            "main_process_pid": None,
            "isolated_server": None,
            "process_pids_distinct": False,
            "protocol": None,
            "samples": [],
            "cycles": [],
            "transitions": [],
            "memory": {"main": None, "isolated": None},
            "summary": None,
        } if args.s2_a is not None else None),
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
        "OBSERVED_S2_PROXY_ONLY", "TEST_FAKE_OBSERVED_S2_PROXY_ONLY",
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
