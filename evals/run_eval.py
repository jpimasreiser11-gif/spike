"""Measure SPIKE specialists: the base model with the specialist prompt vs. the same model plus its adapter.

    python evals/run_eval.py --suites medicine,general \
        --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --adapter ~/.spike/adapters/spike-medicine.gguf \
        [--acceptance training/configs/medicine.yaml] [--limit 200] [--parallel 4] [--ngl 99]

Starts its own llama-server (or uses --server-url), answers every item with greedy decoding and thinking off,
writes predictions.jsonl, summary.json and summary.md under evals/results/<run-id>/ and, with --acceptance,
applies the adapter's acceptance criteria. Nothing is estimated: every number comes from scored answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train import licenses  # noqa: E402
from spike_train.evaluation import Client, Item, check_acceptance, free_port, make_item, score, summarize  # noqa: E402


def load_items(task: dict, registry: dict, seed: int, limit: int | None) -> list[Item]:
    from datasets import load_dataset

    src = registry[task["source"]]
    ok, reason = licenses.check(src["license"], "eval")
    if not ok or src["role"] != "eval":
        raise SystemExit(f"source '{task['source']}' is not an eval source: {reason}")
    ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "test"))
    rows = list(ds)
    if task.get("categories"):
        rows = [r for r in rows if r.get("category") in set(task["categories"])]
    items = [it for i, r in enumerate(rows) if (it := make_item(task["name"], src["format"], i, r))]
    random.Random(seed).shuffle(items)
    if not items:
        raise SystemExit(f"task '{task['name']}' produced no items")
    n = min(x for x in (task.get("n"), limit, len(items)) if x)
    return sorted(items[:n], key=lambda it: it.id)


async def run(args: argparse.Namespace) -> int:
    from spike.runtime.llamacpp_server import LlamaServer, ServerConfig
    from spike.specialists.catalog import load_catalog

    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text())["suites"]
    catalog = load_catalog()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or ROOT / "evals" / "results" / run_id)
    out.mkdir(parents=True, exist_ok=True)

    server = None
    base_url = args.server_url
    if not base_url:
        cfg = ServerConfig(model=Path(args.model).expanduser(), adapters=[Path(a).expanduser() for a in args.adapter],
                           port=free_port(), context=args.ctx_per_slot * args.parallel, parallel=args.parallel,
                           gpu_layers=args.ngl, threads=args.threads, kv_cache_type=args.kv_cache_type)
        server = LlamaServer(cfg)
        print("starting:", " ".join(cfg.command(Path("llama-server"))), file=sys.stderr)
        await server.start()
        base_url = server.base_url
    client = Client(base_url, concurrency=args.parallel)
    try:
        adapters = await client.adapters()
        variants = {"base": client.lora(None)} | {stem: client.lora(stem) for stem in adapters}
        meta = {"run_id": run_id, "model": args.model, "adapters": adapters, "server_url": base_url,
                "parallel": args.parallel, "kv_cache_type": args.kv_cache_type, "max_tokens": args.max_tokens, "seed": args.seed, "decoding": "greedy",
                "thinking": False, "host": platform.platform(), "machine": platform.machine(),
                "props": (await client.http.get(f"{base_url}/props")).json().get("build_info")}
        predictions: list[dict] = []
        pred_file = (out / "predictions.jsonl").open("w", encoding="utf-8")
        for suite_name in args.suites.split(","):
            suite = suites[suite_name]
            system = catalog.get(suite["specialist"]).system_prompt
            for task in suite["tasks"]:
                items = load_items(task, registry, args.seed, args.limit)
                for variant, lora in variants.items():  # one variant at a time: a batch never mixes adapters
                    t0 = time.perf_counter()

                    async def answer(item: Item, lora=lora, variant=variant, system=system, suite_name=suite_name) -> dict:
                        res = await client.chat(system, item.prompt, lora, args.max_tokens, seed=args.seed)
                        parsed, correct = score(item, res["content"])
                        return {"suite": suite_name, "task": item.task, "item": item.id, "variant": variant,
                                "gold": item.gold, "parsed": parsed, "correct": correct, **res,
                                "response": res["content"]}

                    rows = await asyncio.gather(*(answer(it) for it in items))
                    for r in rows:
                        r.pop("content", None)
                        pred_file.write(json.dumps(r, ensure_ascii=False) + "\n")
                    pred_file.flush()
                    predictions.extend(rows)
                    acc = sum(r["correct"] for r in rows) / max(1, len(rows))
                    print(f"{suite_name}/{task['name']} [{variant}] n={len(rows)} acc={acc:.3f} "
                          f"({time.perf_counter() - t0:.0f}s)", file=sys.stderr)
        pred_file.close()
        summary = {"meta": meta, **summarize(predictions)}
        verdicts = {}
        if args.acceptance:
            acceptance = yaml.safe_load(Path(args.acceptance).read_text())["acceptance"]
            for variant in variants:
                if variant != "base":
                    ok, reasons = check_acceptance(summary, acceptance, variant)
                    verdicts[variant] = {"accepted": ok, "reasons": reasons}
            summary["acceptance"] = verdicts
        (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        (out / "summary.md").write_text(render_markdown(summary))
        print((out / "summary.md").read_text())
        print(f"results: {out}", file=sys.stderr)
        return 0 if all(v["accepted"] for v in verdicts.values()) else 2
    finally:
        await client.aclose()
        if server:
            await server.stop()


def render_markdown(summary: dict) -> str:
    meta = summary["meta"]
    lines = [f"# SPIKE eval {meta['run_id']}", "",
             f"Model `{Path(meta['model'] or '').name}`, llama.cpp `{meta.get('props')}`, greedy, thinking off, "
             f"max_tokens {meta['max_tokens']}, host `{meta['host']}`.", "",
             "| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |",
             "|---|---|---|---|---|---|---|---|---|"]
    for level in ("tasks", "suites"):
        for name, entry in summary[level].items():
            for variant, acc in entry["accuracy"].items():
                cmp = entry["vs_base"].get(variant)
                label = name if level == "tasks" else f"**{name} (pooled)**"
                delta = "{:+.2f}".format(cmp["delta_points"]) if cmp else ""
                p_value = "{:.4g}".format(cmp["p_value"]) if cmp else ""
                lo, hi = acc["ci95"]
                lines.append(f"| {label} | {variant} | {acc['n']} | {acc['accuracy']:.3f} | {lo:.3f}–{hi:.3f} | "
                             f"{delta} | {p_value} | {acc['unparsed']} | {acc['truncated']} |")
    for variant, v in (summary.get("acceptance") or {}).items():
        lines += ["", f"**{variant}: {'ACCEPTED' if v['accepted'] else 'REJECTED'}**", *[f"- {r}" for r in v["reasons"]]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", required=True, help="comma-separated names from evals/suites.yaml")
    ap.add_argument("--model", help="base GGUF (required unless --server-url)")
    ap.add_argument("--adapter", action="append", default=[], help="GGUF LoRA; repeatable")
    ap.add_argument("--server-url", help="use a running llama-server instead of starting one")
    ap.add_argument("--acceptance", help="training config whose `acceptance` block decides the verdict")
    ap.add_argument("--limit", type=int, help="max items per task (quick runs)")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--ctx-per-slot", type=int, default=4096)
    ap.add_argument("--ngl", type=int, default=99, help="GPU layers (99 on Apple Silicon, 0 for CPU only)")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--kv-cache-type", default="q8_0", help="same default as the SPIKE runtime")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out")
    args = ap.parse_args()
    if not args.server_url and not args.model:
        ap.error("--model is required unless --server-url is given")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
