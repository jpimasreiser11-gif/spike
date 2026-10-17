"""Reproducible performance benchmark for a GGUF model served by llama-server.

Measures, per prompt length: time to first token (TTFT), prompt processing speed, generation speed and
peak resident memory of the server process. All numbers come from the real process on this machine;
the report records hardware, versions and settings so results can be compared and reproduced.
"""

from __future__ import annotations

import asyncio
import json
import platform
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import psutil

from spike import __version__
from spike.providers.llamacpp import explicit_lora
from spike.runtime.hardware import detect
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig

SAMPLE_TEXT = (
    "The quarterly report shows revenue growth driven by new customers in Europe, while operating costs "
    "rose because of hiring in engineering. Analysts expect margins to recover next year as the product "
    "line matures. Meanwhile, the clinical team reviewed patient outcomes and found that early diagnosis "
    "reduced hospital stays. The marketing department launched a campaign targeting small businesses. "
)


class RSSSampler:
    def __init__(self, pid: int, interval: float = 0.1):
        self.proc = psutil.Process(pid)
        self.interval = interval
        self.peak = 0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            try:
                self.peak = max(self.peak, self.proc.memory_info().rss)
            except psutil.Error:
                return
            await asyncio.sleep(self.interval)

    def __enter__(self) -> RSSSampler:
        self._task = asyncio.get_running_loop().create_task(self._run())
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._task:
            self._task.cancel()


async def prompt_tokens(client: httpx.AsyncClient, base: str, n: int) -> list[int]:
    ids = (await client.post(f"{base}/tokenize", json={"content": SAMPLE_TEXT})).json()["tokens"]
    reps = n // len(ids) + 1
    return (ids * reps)[:n]


async def one_run(client: httpx.AsyncClient, base: str, tokens: list[int], gen: int, lora: list) -> dict[str, Any]:
    body = {"prompt": tokens, "n_predict": gen, "stream": True, "cache_prompt": False, "temperature": 0.0,
            "ignore_eos": True}
    if lora:
        body["lora"] = lora
    t0 = time.perf_counter()
    ttft = None
    timings: dict[str, Any] = {}
    async with client.stream("POST", f"{base}/completion", json=body) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            if ttft is None and data.get("content"):
                ttft = time.perf_counter() - t0
            if data.get("stop"):
                timings = data.get("timings", {})
    wall = time.perf_counter() - t0
    return {
        "ttft_s": round(ttft or wall, 4),
        "prompt_tokens": timings.get("prompt_n"),
        "prompt_tok_s": round(timings.get("prompt_per_second", 0.0), 2),
        "gen_tokens": timings.get("predicted_n"),
        "gen_tok_s": round(timings.get("predicted_per_second", 0.0), 2),
        "wall_s": round(wall, 3),
    }


def _summary(runs: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [r[key] for r in runs if r.get(key) is not None]
    return {"median": round(statistics.median(values), 4), "min": min(values), "max": max(values)} if values else {}


async def run_benchmark(args: Any) -> dict[str, Any]:
    contexts = [int(x) for x in str(args.contexts).split(",") if x]
    model = Path(args.model).expanduser()
    adapters = [Path(a).expanduser() for a in args.adapter]
    config = ServerConfig(model=model, adapters=adapters, port=args.port, context=max(contexts) + args.gen + 256,
                          threads=args.threads, gpu_layers=args.gpu_layers, kv_cache_type=args.kv)
    server = LlamaServer(config)
    hw = detect()
    report: dict[str, Any] = {
        "spike_version": __version__,
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardware": hw.to_dict(),
        "python": platform.python_version(),
        "model": {"path": str(model), "file_gb": round(model.stat().st_size / 1024**3, 3)},
        "settings": {"contexts": contexts, "gen": args.gen, "repeats": args.repeats, "threads": args.threads,
                     "gpu_layers": args.gpu_layers, "kv_cache_type": args.kv, "server_context": config.context},
        "results": [],
    }
    await server.start()
    report["load_seconds"] = server.load_seconds
    base = server.base_url
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
            props = (await client.get(f"{base}/props")).json()
            report["llama_cpp_build"] = props.get("build_info")
            report["idle_rss_mb"] = server.memory_rss_mb()
            ids = range(len(adapters))  # explicit scales: an empty list means "global scales", not "base"
            variants: list[tuple[str, list]] = [("base", explicit_lora(ids, None))]
            if adapters:
                variants.append((adapters[0].stem, explicit_lora(ids, 0)))
            await one_run(client, base, await prompt_tokens(client, base, 32), 8, variants[0][1])  # warm-up
            for n in contexts:
                tokens = await prompt_tokens(client, base, n)
                for name, lora in variants:
                    runs = []
                    with RSSSampler(server.process.pid) as sampler:
                        for _ in range(args.repeats):
                            runs.append(await one_run(client, base, tokens, args.gen, lora))
                    report["results"].append({
                        "prompt_tokens": n, "variant": name, "runs": runs,
                        "ttft_s": _summary(runs, "ttft_s"), "prompt_tok_s": _summary(runs, "prompt_tok_s"),
                        "gen_tok_s": _summary(runs, "gen_tok_s"), "peak_rss_mb": round(sampler.peak / 1024**2, 1),
                    })
    finally:
        await server.stop()
    if getattr(args, "out", None):
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2))
    return report


def as_dict(obj: Any) -> Any:
    return asdict(obj)
