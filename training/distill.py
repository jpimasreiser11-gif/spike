"""Generate verified teacher data for one specialist.

    # 1. serve the teacher locally (36 GB Mac), e.g.
    mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090
    # 2. distill
    python training/distill.py training/configs/science.yaml --out training/data/science/distilled.jsonl

The recipe's `distill` block names exactly one source of tasks (spike_train/seeding.py), because no text written by an
AI assistant may become training data:
  distill.topics      a file of short topic labels with a provenance header. The open teacher writes every task from
                      them (`distill.kinds` says which: open, explanation, mcq, sql) and then the answers; a label is an
                      instruction to the teacher and never appears in a row. Checks per kind: spike_train/synth.py
  distill.seeds       example tasks the teacher expands to `distill.expand_to` variants; refused unless the file declares
                      a human author in its first line
  distill.tasks_from  training-split questions with gold answers, verified by exact match
The teacher's Hub license must be on the training allowlist (spike_train/licenses.py), checked before any task is sent;
every row records the teacher's repo and license and how its tasks were made, and prepare.py checks them again. The
recipe's `distill.teacher` names the repo (and the name it is served under); --teacher-model and --teacher-repo override it,
and a different --teacher-model with no --teacher-repo is licensed under its own name, never under the recipe's.
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

from spike_train import licenses, seeding  # noqa: E402
from spike_train.data import LETTERS, dedupe, mcq_prompt  # noqa: E402
from spike_train.distill import Task, Teacher, distill_task  # noqa: E402
from spike_train.sources import hub_load_kwargs  # noqa: E402
from spike_train.synth import MAX_STALLS, PER_CALL, generate  # noqa: E402

DEFAULT_TEACHER = "mlx-community/Qwen3.6-35B-A3B-4bit"

EXPAND = (
    "Here are example tasks that real users bring to a {domain} expert:\n\n{examples}\n\n"
    "Write {n} NEW tasks of the same kind: realistic, specific (numbers, context, constraints), varied in "
    "difficulty, industry and language (about 30% in Spanish). One task per line, no numbering, no answers."
)


async def expand_seeds(teacher: Teacher, seeds: list[str], domain: str, target: int, seed: int) -> list[str]:
    """Grow `seeds` to `target` distinct tasks. Stops with an error when the teacher keeps returning duplicates (or
    nothing): MAX_STALLS calls in a row without a new task, or three times the calls a duplicate-free teacher needs."""
    rng = random.Random(seed)
    tasks = list(seeds)
    seen = {t.strip().lower() for t in tasks}
    max_calls = 3 * -(-max(0, target - len(tasks)) // PER_CALL) + MAX_STALLS
    calls = stalls = 0
    while len(tasks) < target:
        if stalls >= MAX_STALLS or calls >= max_calls:
            raise SystemExit(f"the teacher gave only {len(tasks)} distinct tasks of the {target} asked for "
                             f"(distill.expand_to) in {calls} calls; lower expand_to, add seeds, or check the teacher")
        calls += 1
        examples = "\n".join(f"- {s}" for s in rng.sample(tasks, min(8, len(tasks))))
        prompt = EXPAND.format(domain=domain, examples=examples, n=PER_CALL)
        content, _ = await teacher.chat([{"role": "user", "content": prompt}], temperature=1.0, thinking=False)
        before = len(tasks)
        for line in content.splitlines():
            line = line.strip().lstrip("-•*0123456789. ").strip()
            if len(line) > 25 and line.lower() not in seen:
                seen.add(line.lower())
                tasks.append(line)
        stalls = 0 if len(tasks) > before else stalls + 1
    return tasks[:target]


def gold_tasks(entry: dict, registry: dict, system: str) -> list[Task]:
    from datasets import load_dataset

    src = registry[entry["source"]]
    ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "train"), streaming=True,
                      **hub_load_kwargs(src))
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


def resolve_teacher(args: argparse.Namespace, dcfg: dict) -> tuple[str, str]:
    """(the name the teacher is served under, the Hub repo whose license governs its outputs). The recipe's
    `distill.teacher` supplies both unless --teacher-model names another model; then, without --teacher-repo, the
    repo is that model's own name."""
    named = dcfg.get("teacher") or {}
    if named and not (isinstance(named, dict) and isinstance(named.get("repo"), str)):
        raise SystemExit("distill.teacher must be {repo: <Hub repo>, served_as: <name the server uses>}")
    model = args.teacher_model or named.get("served_as") or named.get("repo") or DEFAULT_TEACHER
    recipe_model = args.teacher_model is None
    return model, args.teacher_repo or (named.get("repo") if recipe_model else None) or model


async def run(args: argparse.Namespace) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    from spike.specialists.catalog import load_catalog

    spec = load_catalog().get(cfg["specialist"])
    dcfg = cfg.get("distill") or {}
    try:  # before any task is sent
        plan = seeding.resolve(dcfg, ROOT)
    except seeding.SeedingError as exc:
        raise SystemExit(str(exc)) from exc
    model, repo = resolve_teacher(args, dcfg)
    try:  # the teacher's terms apply to everything it writes
        teacher_license = licenses.teacher_license(repo)
    except ValueError as exc:
        raise SystemExit(f"refusing to distill: {exc} (--teacher-repo names the Hub repo of the weights)") from exc
    provenance = {"teacher": repo, "teacher_license": teacher_license}
    teacher = Teacher(args.teacher_url, model, concurrency=args.concurrency)
    target = args.limit or dcfg.get("expand_to", 1000)
    try:
        results: list[dict] = []
        summary: dict = {}
        if plan.mode == "topics":
            try:
                results, kept_by_kind, dropped = await generate(
                    teacher, spec, list(plan.topics.items), dcfg.get("kinds") or {"open": 1}, target, cfg.get("seed", 0),
                    min_score=dcfg.get("min_score", 8), samples=args.samples, keep_reasoning=args.keep_reasoning,
                    progress=lambda message: print(message, file=sys.stderr))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            tasks = range(target)
            summary = {"kept_by_kind": dict(kept_by_kind), "dropped": dict(sorted(dropped.items()))}
        else:
            if plan.mode == "seeds":
                prompts = await expand_seeds(teacher, list(plan.seeds.prompts), spec.domain, target, cfg.get("seed", 0))
                tasks = [Task(id=f"{spec.id}-{i}", prompt=p, system=spec.system_prompt) for i, p in enumerate(prompts)]
            else:
                tasks = gold_tasks(plan.gold, registry, spec.system_prompt)
                tasks = tasks[: args.limit] if args.limit else tasks
            print(f"{len(tasks)} tasks", file=sys.stderr)
            kept = 0
            for i in range(0, len(tasks), 32):
                batch = await asyncio.gather(*[
                    distill_task(teacher, t, samples=args.samples, min_score=dcfg.get("min_score", 8),
                                 keep_reasoning=args.keep_reasoning) for t in tasks[i:i + 32]])
                results += [r for r in batch if r]
                kept = len(results)
                print(f"  {i + len(batch)}/{len(tasks)} processed, {kept} kept", file=sys.stderr)
        for r in results:
            r["meta"].update(provenance)
            r["meta"]["seeding"] = plan.record
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for r in dedupe(results):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps({"tasks": len(tasks), "kept": len(results),
                          "verified_against_gold": sum(r["meta"]["verified"] for r in results),
                          "teacher": model, **provenance, "seeding": plan.record, **summary, "out": str(out)}, indent=2))
    finally:
        await teacher.aclose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--teacher-url", default="http://127.0.0.1:8090/v1")
    ap.add_argument("--teacher-model", help=f"name the server uses (default: the recipe's distill.teacher.served_as, else "
                                            f"{DEFAULT_TEACHER})")
    ap.add_argument("--teacher-repo", help="Hugging Face repo whose license governs the teacher's outputs "
                                           "(default: the recipe's distill.teacher.repo, else --teacher-model, which is a "
                                           "repo id for mlx_lm.server)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=2, help="attempts per task (rejection sampling)")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--keep-reasoning", action="store_true", help="keep teacher reasoning in <think> tags")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
