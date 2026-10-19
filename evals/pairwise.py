"""Pairwise judged comparison for open-ended specialists (e.g. marketing), base vs. adapter.

    # judge: a stronger local open model behind an OpenAI-compatible endpoint (no paid API)
    mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090
    # general regression suite, base vs. adapter (same as medicine and finance)
    python evals/run_eval.py --suites general --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf \
        --adapter ~/.spike/adapters/spike-marketing.gguf --out evals/results/general-marketing
    python evals/pairwise.py --specialist marketing --prompts evals/data/marketing_eval.jsonl \
        --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --adapter ~/.spike/adapters/spike-marketing.gguf \
        [--acceptance training/configs/marketing.yaml --general-eval evals/results/general-marketing]

Base and adapter answer greedily (temperature 0, thinking off) like run_eval.py; --temperature changes it and is
recorded. Each prompt is judged twice with the answers in swapped positions; a side wins only when both orders
agree, otherwise it is a tie (removes position bias). With --acceptance the round is accepted only if the win
rate and sign test pass AND the general suite dropped by no more than the config's regression limit (exit code 2
otherwise). Caveat recorded in the output: the judge is also the distillation teacher, so it may prefer the
adapter's style (self-preference bias); confirm with human review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train.distill import Teacher  # noqa: E402
from spike_train.evaluation import (  # noqa: E402
    Client,
    check_pairwise_acceptance,
    free_port,
    general_regression,
    pairwise_summary,
)

JUDGE = (
    "You compare two answers to the same request from a professional {domain} client. Judge usefulness: "
    "correctness, specificity, actionability, honesty about uncertainty, and following the request. Ignore length "
    "unless it hurts usefulness. Penalize invented facts or numbers. Reply with JSON only: "
    '{{"better": "A" | "B" | "tie", "reason": "<one sentence>"}}'
)


async def judge(teacher: Teacher, domain: str, prompt: str, a: str, b: str) -> str:
    content, _ = await teacher.chat(
        [{"role": "system", "content": JUDGE.format(domain=domain)},
         {"role": "user", "content": f"REQUEST:\n{prompt}\n\nANSWER A:\n{a}\n\nANSWER B:\n{b}"}],
        temperature=0.0, max_tokens=200, thinking=False)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        return str(json.loads(m.group(0))["better"]).strip().upper() if m else "TIE"
    except (ValueError, KeyError):
        return "TIE"


def load_general(path: str, suite: str, variant: str) -> dict:
    """The regression suite's base-vs-adapter result from a run_eval.py run (its directory or summary.json)."""
    file = Path(path) / "summary.json" if Path(path).is_dir() else Path(path)
    if not file.is_file():
        raise SystemExit(f"no general eval results at {file}; run evals/run_eval.py --suites {suite} first")
    try:
        return {**general_regression(json.loads(file.read_text(encoding="utf-8")), suite, variant), "run": str(file)}
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


async def run(args: argparse.Namespace) -> int:
    from spike.runtime.llamacpp_server import LlamaServer, ServerConfig
    from spike.specialists.catalog import load_catalog

    acceptance = yaml.safe_load(Path(args.acceptance).read_text(encoding="utf-8"))["acceptance"] if args.acceptance else None
    general = None
    if acceptance and acceptance.get("regression"):  # fail before hours of generation, not after
        if not args.general_eval:
            raise SystemExit(f"{args.acceptance} has a regression limit on '{acceptance['regression']['suite']}': "
                             "pass --general-eval with the run_eval.py run of that suite for this adapter")
        general = load_general(args.general_eval, acceptance["regression"]["suite"],
                               Path(args.adapter).expanduser().stem)
    spec = load_catalog().get(args.specialist)
    prompts = [json.loads(line) for line in Path(args.prompts).read_text(encoding="utf-8").splitlines() if line.strip()]
    out = Path(args.out or ROOT / "evals" / "results" / f"pairwise-{args.specialist}-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    cfg = ServerConfig(model=Path(args.model).expanduser(), adapters=[Path(args.adapter).expanduser()], port=free_port(),
                       context=args.ctx_per_slot * args.parallel, parallel=args.parallel, gpu_layers=args.ngl)
    server = LlamaServer(cfg)
    await server.start()
    client = Client(server.base_url, concurrency=args.parallel)
    teacher = Teacher(args.judge_url, args.judge_model, concurrency=2)
    try:
        (stem, _), = (await client.adapters()).items()

        async def generate(p: dict, lora: list) -> str:
            res = await client.chat(spec.system_prompt, p["prompt"], lora, args.max_tokens,
                                    temperature=args.temperature, seed=args.seed)
            return res["content"]

        base = await asyncio.gather(*(generate(p, client.lora(None)) for p in prompts))
        cand = await asyncio.gather(*(generate(p, client.lora(stem)) for p in prompts))
        rows, verdicts = [], []
        for p, b, c in zip(prompts, base, cand, strict=True):
            first = await judge(teacher, spec.domain, p["prompt"], b, c)   # candidate is B
            second = await judge(teacher, spec.domain, p["prompt"], c, b)  # candidate is A
            verdict = "win" if (first, second) == ("B", "A") else "loss" if (first, second) == ("A", "B") else "tie"
            verdicts.append(verdict)
            rows.append({"id": p.get("id"), "prompt": p["prompt"], "base": b, "adapter": c,
                         "judge_orders": [first, second], "verdict": verdict})
        summary = {"specialist": args.specialist, "adapter": stem, "judge": args.judge_model,
                   "temperature": args.temperature, "seed": args.seed, **pairwise_summary(verdicts),
                   "caveat": "judge is also the distillation teacher; possible self-preference bias"}
        if acceptance:  # accepted only if the win rate AND the general-suite drop pass
            if general:
                summary["general"] = general
            summary["accepted"], summary["reasons"] = check_pairwise_acceptance(summary, acceptance)
        (out / "pairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary.get("accepted", True) else 2
    finally:
        await teacher.aclose()
        await client.aclose()
        await server.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specialist", required=True)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--judge-url", default="http://127.0.0.1:8090/v1")
    ap.add_argument("--judge-model", default="mlx-community/Qwen3.6-35B-A3B-4bit")
    ap.add_argument("--acceptance", help="training config whose `acceptance` block decides the verdict")
    ap.add_argument("--general-eval", metavar="RUN_DIR",
                    help="run_eval.py run (directory or summary.json) of the config's regression suite, base vs. "
                         "this adapter; required when the acceptance block has a regression limit")
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--temperature", type=float, default=0.0, help="0 = greedy, as in run_eval.py")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--ctx-per-slot", type=int, default=4096)
    ap.add_argument("--ngl", type=int, default=99)
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.general_eval and not args.acceptance:
        ap.error("--general-eval needs --acceptance (the config names the regression suite and its limit)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
