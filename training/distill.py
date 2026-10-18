"""Generate verified teacher data for one specialist.

    # 1. serve the teacher locally (36 GB Mac), e.g.
    mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090
    # 2. distill
    python training/distill.py training/configs/marketing.yaml --teacher-url http://127.0.0.1:8090/v1 \
        --teacher-model mlx-community/Qwen3.6-35B-A3B-4bit --out training/data/marketing/distilled.jsonl

Tasks come from `distill.seeds` (expanded by the teacher to `distill.expand_to` variants) or from
`distill.tasks_from` (training-split questions with gold answers, verified by exact match).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train.data import LETTERS, dedupe, mcq_prompt  # noqa: E402
from spike_train.distill import Task, Teacher, distill_task  # noqa: E402

EXPAND = (
    "Here are example tasks that real users bring to a {domain} expert:\n\n{examples}\n\n"
    "Write {n} NEW tasks of the same kind: realistic, specific (numbers, context, constraints), varied in "
    "difficulty, industry and language (about 30% in Spanish). One task per line, no numbering, no answers."
)


async def expand_seeds(teacher: Teacher, seeds: list[str], domain: str, target: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    tasks = list(seeds)
    seen = {t.strip().lower() for t in tasks}
    while len(tasks) < target:
        examples = "\n".join(f"- {s}" for s in rng.sample(tasks, min(8, len(tasks))))
        content, _ = await teacher.chat([{"role": "user", "content": EXPAND.format(domain=domain, examples=examples, n=20)}],
                                        temperature=1.0, thinking=False)
        for line in content.splitlines():
            line = line.strip().lstrip("-•*0123456789. ").strip()
            if len(line) > 25 and line.lower() not in seen:
                seen.add(line.lower())
                tasks.append(line)
    return tasks[:target]


def gold_tasks(entry: dict, registry: dict, system: str) -> list[Task]:
    from datasets import load_dataset

    src = registry[entry["source"]]
    ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "train"), streaming=True)
    tasks: list[Task] = []
    for i, row in enumerate(ds):
        if i < entry.get("offset", 0):
            continue
        if len(tasks) >= entry.get("max", 1000):
            break
        if src["format"] == "medmcqa" and row.get("cop") is not None and row.get("choice_type") != "multi":
            options = [row[k] for k in ("opa", "opb", "opc", "opd")]
            tasks.append(Task(id=f"{entry['source']}-{i}", prompt=mcq_prompt(row["question"], options), system=system,
                              gold={"type": "mcq", "answer": LETTERS[int(row["cop"])]}))
    return tasks


async def run(args: argparse.Namespace) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text())
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    from spike.specialists.catalog import load_catalog

    spec = load_catalog().get(cfg["specialist"])
    dcfg = cfg.get("distill") or {}
    teacher = Teacher(args.teacher_url, args.teacher_model, concurrency=args.concurrency)
    try:
        if dcfg.get("seeds"):
            seeds = [json.loads(line)["prompt"] for line in (ROOT / dcfg["seeds"]).read_text().splitlines() if line.strip()]
            prompts = await expand_seeds(teacher, seeds, spec.domain, args.limit or dcfg.get("expand_to", 1000), cfg.get("seed", 0))
            tasks = [Task(id=f"{spec.id}-{i}", prompt=p, system=spec.system_prompt) for i, p in enumerate(prompts)]
        elif dcfg.get("tasks_from"):
            tasks = gold_tasks(dcfg["tasks_from"], registry, spec.system_prompt)
            tasks = tasks[: args.limit] if args.limit else tasks
        else:
            raise SystemExit("config has no distill.seeds or distill.tasks_from")
        print(f"{len(tasks)} tasks", file=sys.stderr)
        results = []
        kept = verified = 0
        for i in range(0, len(tasks), 32):
            batch = await asyncio.gather(*[
                distill_task(teacher, t, samples=args.samples, min_score=dcfg.get("min_score", 8),
                             keep_reasoning=args.keep_reasoning) for t in tasks[i:i + 32]])
            for r in batch:
                if r:
                    results.append(r)
                    kept += 1
                    verified += r["meta"]["verified"]
            print(f"  {i + len(batch)}/{len(tasks)} processed, {kept} kept", file=sys.stderr)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for r in dedupe(results):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps({"tasks": len(tasks), "kept": kept, "verified_against_gold": verified,
                          "teacher": args.teacher_model, "out": str(out)}, indent=2))
    finally:
        await teacher.aclose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--teacher-url", default="http://127.0.0.1:8090/v1")
    ap.add_argument("--teacher-model", default="mlx-community/Qwen3.6-35B-A3B-4bit")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=2, help="attempts per task (rejection sampling)")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--keep-reasoning", action="store_true", help="keep teacher reasoning in <think> tags")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
