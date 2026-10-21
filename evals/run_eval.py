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
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train import licenses  # noqa: E402
from spike_train.evaluation import (  # noqa: E402
    Client,
    Item,
    check_acceptance,
    free_port,
    make_item,
    rescore,
    reusable_rows,
    score,
    summarize,
)
from spike_train.sources import filtered, url_rows  # noqa: E402


def load_items(task: dict, registry: dict, seed: int, limit: int | None) -> list[Item]:
    src = registry[task["source"]]
    ok, reason = licenses.check(licenses.source_license(src), "eval")  # Hub: as published; URL source: as recorded
    if not ok or src["role"] != "eval":
        raise SystemExit(f"source '{task['source']}' is not an eval source: {reason}")
    if "urls" in src:  # pinned files instead of the Hub (spike_train/sources.py)
        ds = url_rows(src)
    else:
        from datasets import load_dataset

        ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "test"))
    rows = list(filtered(src, ds))
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

    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
    catalog = load_catalog()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.resume or args.out or ROOT / "evals" / "results" / run_id)
    saved: list[dict] = []
    if args.resume:  # an interrupted run: keep its complete (task, variant) groups, generate the rest
        saved = [json.loads(line) for line in (out / "predictions.jsonl").open(encoding="utf-8")]
        run_id = out.name
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
                "parallel": args.parallel, "kv_cache_type": args.kv_cache_type, "max_tokens": args.max_tokens, "seed": args.seed, "limit": args.limit, "suites": args.suites, "decoding": "greedy",
                "thinking": False, "host": platform.platform(), "machine": platform.machine(),
                "props": (await client.http.get(f"{base_url}/props")).json().get("build_info")}
        if args.resume:
            meta["resumed"] = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "saved_rows": len(saved)}
        predictions: list[dict] = []
        pred_file = (out / "predictions.jsonl").open("w", encoding="utf-8")
        for suite_name in args.suites.split(","):
            suite = suites[suite_name]
            system = catalog.get(suite["specialist"]).system_prompt
            for task in suite["tasks"]:
                items = load_items(task, registry, args.seed, args.limit)
                for variant, lora in variants.items():  # one variant at a time: a batch never mixes adapters
                    t0 = time.perf_counter()
                    reused = reusable_rows(saved, suite_name, task["name"], variant, [it.id for it in items])
                    if reused is not None:
                        for r in reused:
                            pred_file.write(json.dumps(r, ensure_ascii=False) + "\n")
                        predictions.extend(reused)
                        print(f"{suite_name}/{task['name']} [{variant}] n={len(reused)} reused from the interrupted run",
                              file=sys.stderr)
                        continue

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
        return write_summary(out, meta, predictions, list(variants), args.acceptance)
    finally:
        await client.aclose()
        if server:
            await server.stop()


def write_summary(out: Path, meta: dict, predictions: list[dict], variants: list[str],
                  acceptance_file: str | None) -> int:
    summary = {"meta": meta, **summarize(predictions)}
    verdicts = {}
    if acceptance_file:
        acceptance = yaml.safe_load(Path(acceptance_file).read_text(encoding="utf-8"))["acceptance"]
        for variant in variants:
            if variant != "base":
                ok, reasons = check_acceptance(summary, acceptance, variant)
                verdicts[variant] = {"accepted": ok, "reasons": reasons}
        summary["acceptance"] = verdicts
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print((out / "summary.md").read_text(encoding="utf-8"))
    print(f"results: {out}", file=sys.stderr)
    return 0 if all(v["accepted"] for v in verdicts.values()) else 2


def rescore_run(args: argparse.Namespace) -> int:
    """Re-score a finished run's saved responses with the current answer extractors. No model is run;
    the same items are rebuilt from the run's seed and every saved prediction must match one of them."""
    out = Path(args.rescore)
    meta = json.loads((out / "summary.json").read_text(encoding="utf-8"))["meta"]
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
    old = [json.loads(line) for line in (out / "predictions.jsonl").open(encoding="utf-8")]
    items: dict[str, Item] = {}
    for suite_name in sorted({p["suite"] for p in old}):
        for task in suites[suite_name]["tasks"]:
            items.update({it.id: it for it in load_items(task, registry, meta["seed"], meta.get("limit", args.limit))})
    new = rescore(old, items)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    meta["rescored"] = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "git_commit": commit,
                        "rows": len(new), "parsed_changed": sum(a["parsed"] != b["parsed"] for a, b in zip(old, new, strict=True)),
                        "correct_changed": sum(a["correct"] != b["correct"] for a, b in zip(old, new, strict=True))}
    with (out / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    variants = sorted({p["variant"] for p in new}, key=lambda v: (v != "base", v))
    return write_summary(out, meta, new, variants, args.acceptance)


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
    ap.add_argument("--suites", help="comma-separated names from evals/suites.yaml (required unless --rescore)")
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
    ap.add_argument("--resume", metavar="RUN_DIR",
                    help="finish an interrupted run in RUN_DIR with the same arguments: complete groups are reused")
    ap.add_argument("--rescore", metavar="RUN_DIR",
                    help="re-score a finished run's predictions.jsonl with the current extractors (no model run)")
    args = ap.parse_args()
    if args.rescore:
        return rescore_run(args)
    if not args.suites:
        ap.error("--suites is required")
    if not args.server_url and not args.model:
        ap.error("--model is required unless --server-url is given")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
