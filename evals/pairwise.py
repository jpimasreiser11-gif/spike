"""Pairwise judged comparison for open-ended specialists (e.g. marketing), base vs. adapter.

    # judge: a stronger local open model behind an OpenAI-compatible endpoint (no paid API)
    mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090
    # general regression suite, base vs. adapter (same as medicine and finance)
    python evals/run_eval.py --suites general --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf \
        --adapter ~/.spike/adapters/spike-marketing.gguf --out evals/results/general-marketing
    python evals/pairwise.py --specialist marketing --prompts evals/data/marketing_eval.jsonl \
        --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --adapter ~/.spike/adapters/spike-marketing.gguf \
        [--acceptance training/configs/marketing.yaml --general-eval evals/results/general-marketing] [--out DIR]

Base and adapter answer greedily (temperature 0, thinking off) like run_eval.py; --temperature changes it and is
recorded. Each prompt is judged twice with the answers in swapped positions; a side wins only when both orders
agree, otherwise it is a tie (removes position bias). With --acceptance the round is accepted only if the win
rate and sign test pass AND the general suite dropped by no more than the config's regression limit (exit code 2
otherwise). Caveat recorded in the output: the judge is also the distillation teacher, so it may prefer the
adapter's style (self-preference bias); confirm with human review.

--adapter can be repeated (training/sweep_checkpoints.py compares several candidates on the same prompts): the base
model answers once, every adapter is judged against it, and summary.json has one result per adapter under
`adapters` (only a run with one adapter can carry an acceptance verdict).

Answers (answers.jsonl) and judgments (judgments.jsonl) are kept in --out as they finish, with the inputs they came
from (inputs.json): run the same command again and it does only what is missing; changed inputs are refused. The
answers come first, from llama-server alone; the judge is needed only after. When it cannot be reached the answers
stay and the exit code is 3: start the judge and run the same command again (so the 4B model and the judge need not
be in memory together). Exit codes: 0 done (accepted, with --acceptance), 2 rejected, 3 waiting for the judge, 1 error.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
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

WAITING_FOR_JUDGE = 3
INPUTS_FORMAT = "spike-pairwise-inputs-v1"

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


def verdict_of(first: str, second: str) -> str:
    """`first`: the judge's pick with the adapter as B; `second`: with the adapter as A. Agreement or a tie."""
    return "win" if (first, second) == ("B", "A") else "loss" if (first, second) == ("A", "B") else "tie"


def load_general(path: str, suite: str, variant: str) -> dict:
    """The regression suite's base-vs-adapter result from a run_eval.py run (its directory or summary.json)."""
    file = Path(path) / "summary.json" if Path(path).is_dir() else Path(path)
    if not file.is_file():
        raise SystemExit(f"no general eval results at {file}; run evals/run_eval.py --suites {suite} first")
    try:
        return {**general_regression(json.loads(file.read_text(encoding="utf-8")), suite, variant), "run": str(file)}
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def file_hash(path: Path) -> str:
    """In bounded chunks: the base GGUF must not be loaded into RAM."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()  # the same record on every machine
    except ValueError:
        return str(path)


def load_prompts(path: Path) -> list[dict]:
    """{"id", "prompt"} rows; a row without an id gets its line number. Ids must be unique: answers are kept by id."""
    prompts, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row.get("prompt"), str) or not row["prompt"].strip():
            raise SystemExit(f"{path.name}:{n} has no prompt")
        row["id"] = str(row.get("id") or f"line-{n}")
        if row["id"] in seen:
            raise SystemExit(f"{path.name}:{n}: id '{row['id']}' is used twice")
        seen.add(row["id"])
        prompts.append(row)
    if not prompts:
        raise SystemExit(f"{path} has no prompts")
    return prompts


def read_rows(path: Path) -> list[dict]:
    """The rows of a file this script appends to; a last line cut by an interruption is ignored (done again)."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            if n != len(lines):
                raise SystemExit(f"{path}:{n} is not JSON; it was not written by this script") from None
    return rows


def append_row(path: Path, row: dict) -> None:
    """One finished answer or judgment, on disk before the next one starts. A last line cut by an interruption is
    removed first: its row is not done, and is being done again."""
    with path.open("ab+") as f:
        f.seek(0)
        kept = f.read().rfind(b"\n") + 1
        f.truncate(kept)
        f.seek(kept)
        f.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())


def pin_inputs(out: Path, record: dict) -> None:
    """Bind kept answers and judgments to what made them. Adapters may be added to an interrupted run; nothing else
    may change, and no adapter it already has may go (its results stay in the report)."""
    path = out / "inputs.json"
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        same = {k: v for k, v in saved.items() if k != "adapters"} == {k: v for k, v in record.items() if k != "adapters"}
        if not same:
            changed = sorted(k for k in {*saved, *record} - {"adapters"} if saved.get(k) != record.get(k))
            raise SystemExit(f"{out} holds answers made with other inputs ({', '.join(changed)}): use another --out")
        for stem, digest in saved["adapters"].items():
            if stem not in record["adapters"]:
                raise SystemExit(f"{out} has results for {stem}, which this run does not ask for: ask for the same "
                                 "adapters (more may be added), or use another --out")
            if record["adapters"][stem] != digest:
                raise SystemExit(f"{out}: the adapter {stem} changed since its answers were made: use another --out")
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


async def finish_each(coros: list[Awaitable], keep: Callable[[Any], None]) -> None:
    """Run `coros` together and hand each result to `keep` as soon as it is done. On a failure the others are cancelled
    and the failure is raised; what finished is already kept."""
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        for done in asyncio.as_completed(tasks):
            keep(await done)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def answer_missing(prompts: list[dict], variants: list[str], file: Path,
                         generate: Callable[[dict, str], Awaitable[dict]]) -> dict[tuple[str, str], str]:
    """(variant, prompt id) -> answer, generating only what `file` does not have yet, keeping each as it finishes."""
    have = {(r["variant"], r["id"]): r["content"] for r in read_rows(file)}
    missing = [(v, p) for v in variants for p in prompts if (v, p["id"]) not in have]

    async def one(variant: str, prompt: dict) -> tuple[str, dict, dict]:
        return variant, prompt, await generate(prompt, variant)

    def keep(done: tuple[str, dict, dict]) -> None:
        variant, prompt, res = done
        append_row(file, {"variant": variant, "id": prompt["id"], "content": res["content"],
                          "finish_reason": res.get("finish_reason"), "completion_tokens": res.get("completion_tokens")})
        have[variant, prompt["id"]] = res["content"]

    await finish_each([one(v, p) for v, p in missing], keep)
    return have


async def judge_missing(prompts: list[dict], adapters: list[str], answers: dict[tuple[str, str], str], file: Path,
                        decide: Callable[[str, str, str], Awaitable[str]]) -> dict[tuple[str, str], list[str]]:
    """(adapter, prompt id) -> the judge's two picks, judging only what `file` does not have yet."""
    have = {(r["adapter"], r["id"]): r["judge_orders"] for r in read_rows(file)}

    async def one(adapter: str, prompt: dict) -> tuple[str, str, list[str]]:
        base, cand = answers["base", prompt["id"]], answers[adapter, prompt["id"]]
        first = await decide(prompt["prompt"], base, cand)   # adapter is B
        second = await decide(prompt["prompt"], cand, base)  # adapter is A
        return adapter, prompt["id"], [first, second]

    def keep(done: tuple[str, str, list[str]]) -> None:
        adapter, pid, orders = done
        append_row(file, {"adapter": adapter, "id": pid, "judge_orders": orders, "verdict": verdict_of(*orders)})
        have[adapter, pid] = orders

    await finish_each([one(a, p) for a in adapters for p in prompts if (a, p["id"]) not in have], keep)
    return have


async def reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            return (await http.get(f"{url.rstrip('/')}/models")).status_code < 500
    except httpx.HTTPError:
        return False


async def generate_with_server(args: argparse.Namespace, system: str, adapters: dict[str, Path], prompts: list[dict],
                               variants: list[str], file: Path) -> dict[tuple[str, str], str]:
    """Answers from llama-server with every adapter loaded (the base model answers with all of them at scale 0, as in
    run_eval.py); the server starts only when an answer is missing."""
    have = {(r["variant"], r["id"]): r["content"] for r in read_rows(file)}
    if all((v, p["id"]) in have for v in variants for p in prompts):
        return have
    from spike.runtime.llamacpp_server import LlamaServer, ServerConfig

    cfg = ServerConfig(model=Path(args.model).expanduser(), adapters=list(adapters.values()), port=free_port(),
                       context=args.ctx_per_slot * args.parallel, parallel=args.parallel, gpu_layers=args.ngl)
    server = LlamaServer(cfg)
    await server.start()
    client = Client(server.base_url, concurrency=args.parallel)
    try:
        loaded = await client.adapters()
        if set(loaded) != set(adapters):
            raise SystemExit(f"llama-server loaded {sorted(loaded)}, expected {sorted(adapters)}: adapter file names "
                             "must be distinct")

        async def generate(prompt: dict, variant: str) -> dict:
            return await client.chat(system, prompt["prompt"], client.lora(None if variant == "base" else variant),
                                     args.max_tokens, temperature=args.temperature, seed=args.seed)

        return await answer_missing(prompts, variants, file, generate)
    finally:
        await client.aclose()
        await server.stop()


async def run(args: argparse.Namespace) -> int:
    from spike.specialists.catalog import load_catalog

    adapters = {Path(a).expanduser().stem: Path(a).expanduser() for a in args.adapter}
    if len(adapters) != len(args.adapter):
        raise SystemExit("two --adapter files have the same name; answers are kept by file name")
    if "base" in adapters:
        raise SystemExit("an adapter file may not be named base.gguf ('base' is the model without an adapter)")
    acceptance = yaml.safe_load(Path(args.acceptance).read_text(encoding="utf-8"))["acceptance"] if args.acceptance else None
    general = None
    if acceptance and acceptance.get("regression"):  # fail before hours of generation, not after
        if not args.general_eval:
            raise SystemExit(f"{args.acceptance} has a regression limit on '{acceptance['regression']['suite']}': "
                             "pass --general-eval with the run_eval.py run of that suite for this adapter")
        general = load_general(args.general_eval, acceptance["regression"]["suite"], next(iter(adapters)))
    spec = load_catalog().get(args.specialist)
    prompts_path = Path(args.prompts)
    prompts = load_prompts(prompts_path)
    out = Path(args.out or ROOT / "evals" / "results" / f"pairwise-{args.specialist}-{time.strftime('%Y%m%d-%H%M%S')}")
    model = Path(args.model).expanduser()
    for path in (model, *adapters.values()):
        if not path.is_file():
            raise SystemExit(f"not found: {path}")
    pin_inputs(out, {"format": INPUTS_FORMAT, "specialist": args.specialist, "system_prompt": spec.system_prompt,
                     "prompts_sha256": file_hash(prompts_path), "model_sha256": file_hash(model),
                     "adapters": {stem: file_hash(path) for stem, path in adapters.items()},
                     "max_tokens": args.max_tokens, "temperature": args.temperature, "seed": args.seed,
                     "judge": args.judge_model})
    stems = list(adapters)
    answers = await generate_with_server(args, spec.system_prompt, adapters, prompts, ["base", *stems],
                                         out / "answers.jsonl")
    judged = {(r["adapter"], r["id"]) for r in read_rows(out / "judgments.jsonl")}
    if not all((a, p["id"]) in judged for a in stems for p in prompts) and not await reachable(args.judge_url):
        print(f"the answers are kept in {out}; the judge does not answer at {args.judge_url}. Start it "
              f"(mlx_lm.server --model {args.judge_model} --port 8090) and run the same command again.")
        return WAITING_FOR_JUDGE
    teacher = Teacher(args.judge_url, args.judge_model, concurrency=2)
    try:
        picks = await judge_missing(prompts, stems, answers, out / "judgments.jsonl",
                                    lambda prompt, a, b: judge(teacher, spec.domain, prompt, a, b))
    finally:
        await teacher.aclose()

    results, rows = {}, []
    for stem in stems:
        verdicts = []
        for p in prompts:
            orders = picks[stem, p["id"]]
            verdicts.append(verdict_of(*orders))
            rows.append({"id": p["id"], "prompt": p["prompt"], "base": answers["base", p["id"]],
                         "adapter": answers[stem, p["id"]], "judge_orders": orders, "verdict": verdicts[-1],
                         **({"variant": stem} if len(stems) > 1 else {})})
        results[stem] = pairwise_summary(verdicts)
    head = {"specialist": args.specialist, "judge": args.judge_model, "temperature": args.temperature,
            "seed": args.seed, "prompts": shown(prompts_path)}
    caveat = "judge is also the distillation teacher; possible self-preference bias"
    if len(stems) == 1:
        summary = {**head, "adapter": stems[0], **results[stems[0]], "caveat": caveat}
    else:
        summary = {**head, "adapters": results, "caveat": caveat}
    if acceptance:  # accepted only if the win rate AND the general-suite drop pass
        if general:
            summary["general"] = general
        summary["accepted"], summary["reasons"] = check_pairwise_acceptance(summary, acceptance)
    (out / "pairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("accepted", True) else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specialist", required=True)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", required=True, action="append",
                    help="repeatable: every adapter is compared with the base model on the same prompts")
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
    ap.add_argument("--out", help="folder for the answers, judgments and summary; an existing one is continued")
    args = ap.parse_args(argv)
    if args.general_eval and not args.acceptance:
        ap.error("--general-eval needs --acceptance (the config names the regression suite and its limit)")
    if args.acceptance and len(args.adapter) > 1:
        ap.error("--acceptance judges one adapter: give one --adapter")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
