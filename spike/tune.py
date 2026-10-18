"""`spike tune`: measure a few llama-server settings on this machine and keep the fastest that fits.

Threads and KV cache type are measured (generation and prompt speed, peak memory of the real process). The
context length is not measured: it is the largest that fits a share of this machine's RAM by the GGUF's own
numbers (at most 8K without a GPU, where long prompts are slow), and the report says so.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from spike.bench import RSSSampler, one_run, prompt_tokens
from spike.runtime.gguf import kv_cache_bytes, read_gguf
from spike.runtime.hardware import CPU_CONTEXT, HardwareInfo, detect, recommend
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig

CONTEXTS = (8192, 16384, 32768, 65536)
RAM_SHARE = 0.4  # of total RAM for the model, its KV cache and buffers: the rest stays for the user's other apps
OVERHEAD_GB = 0.5  # compute buffers and runtime, as in `spike doctor`
F16_GAIN = 1.10  # f16 KV only when it generates at least 10 % faster than q8_0 (it takes twice the memory)


def thread_candidates(hw: HardwareInfo) -> list[int]:
    cores = max(1, hw.physical_cores)
    options = {cores, max(1, cores - 1), max(1, cores // 2)}
    if hw.logical_cores > cores:
        options.add(hw.logical_cores)
    return sorted(options, reverse=True)


def pick_context(model: Path, kv_cache_type: str, hw: HardwareInfo) -> dict[str, Any]:
    info = read_gguf(model)
    trained = int(info.field("context_length", 0) or 0)
    budget_gb = hw.total_ram_gb * RAM_SHARE
    options = [c for c in CONTEXTS if not trained or c <= trained] or [trained]
    best = options[0]
    for ctx in options:
        if (info.file_size + kv_cache_bytes(info, ctx, kv_cache_type)) / 1024**3 + OVERHEAD_GB <= budget_gb:
            best = ctx
    need = (info.file_size + kv_cache_bytes(info, best, kv_cache_type)) / 1024**3 + OVERHEAD_GB
    return {"context": best, "estimated_gb": round(need, 2), "budget_gb": round(budget_gb, 2), "measured": False}


async def measure(model: Path, threads: int, kv_cache_type: str, gpu_layers: int, *, prompt: int, gen: int,
                  repeats: int, port: int, server_factory: Callable[[ServerConfig], Any] = LlamaServer) -> dict:
    config = ServerConfig(model=model, port=port, context=max(2048, prompt + gen + 64), threads=threads,
                          gpu_layers=gpu_layers, kv_cache_type=kv_cache_type)
    server = server_factory(config)
    if isinstance(getattr(server, "log_path", None), Path):
        server.log_path = server.log_path.with_name("llama-tune.log")  # keep the app engine's own log intact
    await server.start()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1800.0)) as client:
            base = server.base_url
            await one_run(client, base, await prompt_tokens(client, base, 32), 8, [])  # warm-up
            tokens = await prompt_tokens(client, base, prompt)
            with RSSSampler(server.process.pid) as sampler:
                runs = [await one_run(client, base, tokens, gen, []) for _ in range(repeats)]
                sampler.sample()
    finally:
        await server.stop()
    return {"threads": threads, "kv_cache_type": kv_cache_type, "gpu_layers": gpu_layers,
            "gen_tok_s": round(statistics.median(r["gen_tok_s"] for r in runs), 2),
            "prompt_tok_s": round(statistics.median(r["prompt_tok_s"] for r in runs), 2),
            "peak_rss_mb": round(sampler.peak / 1024**2, 1), "runs": runs}


async def tune(model: Path, *, quick: bool = False, hw: HardwareInfo | None = None, threads: list[int] | None = None,
               port: int = 8798, server_factory: Callable[[ServerConfig], Any] = LlamaServer
               ) -> AsyncIterator[dict[str, Any]]:
    """Progress events, then {"type": "tune_done", "best": {...}, "report": {...}}."""
    hw = hw or detect()
    rec = recommend(hw)
    prompt, gen, repeats = (256, 32, 1) if quick else (512, 64, 2)
    candidates = threads or thread_candidates(hw)
    yield {"type": "tune_start", "threads": candidates, "gpu_layers": rec.gpu_layers, "prompt": prompt, "gen": gen}
    started = time.time()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    async def attempt(t: int, kv: str) -> dict[str, Any] | None:
        try:
            result = await measure(model, t, kv, rec.gpu_layers, prompt=prompt, gen=gen, repeats=repeats, port=port,
                                   server_factory=server_factory)
        except (RuntimeError, OSError, TimeoutError, httpx.HTTPError) as exc:  # this setting does not start here
            failures.append({"threads": t, "kv_cache_type": kv, "error": str(exc)[:300]})
            return None
        results.append(result)
        return result

    base_kv = "q8_0"
    for t in candidates:
        result = await attempt(t, base_kv)
        if result is None and base_kv == "q8_0" and not results:
            base_kv = "f16"  # some models cannot use a q8_0 cache (head size not a multiple of 32)
            result = await attempt(t, base_kv)
        yield ({"type": "tune_result", **{k: v for k, v in result.items() if k != "runs"}} if result
               else {"type": "tune_result", **failures[-1], "failed": True})
    if not results:
        raise RuntimeError(f"no setting could start llama-server: {failures[-1]['error'] if failures else ''}")
    best = max(results, key=lambda r: (r["gen_tok_s"], r["prompt_tok_s"]))
    kv = base_kv
    if base_kv == "q8_0":
        f16 = await attempt(best["threads"], "f16")
        yield ({"type": "tune_result", **{k: v for k, v in f16.items() if k != "runs"}} if f16
               else {"type": "tune_result", **failures[-1], "failed": True})
        if f16 and f16["gen_tok_s"] >= best["gen_tok_s"] * F16_GAIN:
            kv = "f16"
    context = pick_context(model, kv, hw)
    if not rec.gpu_layers and context["context"] > CPU_CONTEXT:
        context = {**context, "context": CPU_CONTEXT, "cpu_cap": True}  # long prompts are too slow on CPU (recommend)
    chosen = {"threads": best["threads"], "kv_cache_type": kv, "gpu_layers": rec.gpu_layers,
              "context": context["context"]}
    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - started),
              "hardware": hw.to_dict(), "model": str(model), "prompt_tokens": prompt, "gen_tokens": gen,
              "repeats": repeats, "results": results, "failures": failures, "best": chosen, "context": context}
    yield {"type": "tune_done", "best": chosen, "report": report}


def save_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
