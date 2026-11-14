"""One line per scored answer of a finished `run_eval.py` run, with the question's topic: what the results index and the
Mando benchmark read to say where a specialist fails. No model runs; the answers' text is left out.

    python evals/export_questions.py training/runs/medicine/sweep/final [--no-topics]

Writes `<run>/questions.jsonl`: suite, task, item (the dataset's own question id), variant, topic, gold, parsed,
correct and truncated, sorted. The topic is the dataset's own label: MedMCQA `subject_name`, MMLU-Pro `src` without
its `ori_mmlu-` prefix (the category when there is none); other sources have none (""). Finding the topic loads the
run's eval sources as `run_eval.py` does (the Hub cache on the machine that ran it); `--no-topics` skips that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train.evaluation import make_item  # noqa: E402
from spike_train.provenance import atomic_json  # noqa: E402

FIELDS = ("suite", "task", "item", "variant", "topic", "gold", "parsed", "correct", "truncated")


def topic_of(fmt: str, row: dict) -> str:
    if fmt == "medmcqa":
        return str(row.get("subject_name") or "")
    if fmt == "mmlu_pro":
        src = str(row.get("src") or "")
        return src.removeprefix("ori_mmlu-") or str(row.get("category") or "")
    return ""


def source_rows(task: dict, registry: dict) -> tuple[str, list[dict]]:
    """The rows `run_eval.load_items` numbers, in the same order, so `make_item` gives the same ids."""
    from spike_train import evalfiles
    from spike_train.sources import filtered, hub_load_kwargs, url_rows

    src = registry[task["source"]]
    if "file" in src:
        ds = evalfiles.FORMATS[src["format"]](ROOT / src["file"])
    elif "urls" in src:
        ds = url_rows(src)
    else:
        from datasets import load_dataset

        ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "test"), **hub_load_kwargs(src))
    rows = list(filtered(src, ds))
    if task.get("categories"):
        rows = [r for r in rows if r.get("category") in set(task["categories"])]
    return src["format"], rows


def topics_by_item(tasks: list[dict], registry: dict, load=source_rows) -> dict[str, str]:
    """item id -> topic for every row of these tasks' sources (all rows: no need to repeat the run's sampling)."""
    out: dict[str, str] = {}
    for task in tasks:
        fmt, rows = load(task, registry)
        for i, row in enumerate(rows):
            if (item := make_item(task["name"], fmt, i, row)) is not None:
                out[item.id] = topic_of(fmt, row)
    return out


def run_tasks(summary: dict, suites: dict) -> list[dict]:
    names = str((summary.get("meta") or {}).get("suites") or "").split(",")
    unknown = [n for n in names if n not in suites]
    if not names or unknown:
        raise SystemExit(f"the run's suites are not in evals/suites.yaml: {', '.join(unknown) or '(none recorded)'}")
    return [task for name in names for task in suites[name]["tasks"]]


def export(run: Path, topics: dict[str, str] | None) -> list[dict]:
    rows = []
    with (run / "predictions.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            r = json.loads(line)
            topic = "" if topics is None else topics.get(r["item"])
            if topic is None:
                raise SystemExit(f"{r['item']}: not in the eval source any more (did the dataset change?)")
            rows.append({"suite": r["suite"], "task": r["task"], "item": r["item"].split("/", 1)[-1],
                         "variant": r["variant"], "topic": topic, "gold": r["gold"], "parsed": r["parsed"],
                         "correct": bool(r["correct"]), "truncated": r.get("finish_reason") == "length"})
    rows.sort(key=lambda r: (r["suite"], r["task"], r["variant"], r["item"]))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", type=Path, help="a finished run_eval.py folder (summary.json and predictions.jsonl)")
    ap.add_argument("--no-topics", action="store_true", help="do not load the eval sources; every topic is ''")
    args = ap.parse_args(argv)
    if not (args.run / "summary.json").is_file() or not (args.run / "predictions.jsonl").is_file():
        raise SystemExit(f"{args.run}: needs summary.json and predictions.jsonl from evals/run_eval.py")
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    topics = None
    if not args.no_topics:
        registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
        suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
        topics = topics_by_item(run_tasks(summary, suites), registry)
    rows = export(args.run, topics)
    path = args.run / "questions.jsonl"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    atomic_json(args.run / "questions.json", {"format": "spike-eval-questions-v1", "rows": len(rows),
                                             "topics": not args.no_topics, "fields": list(FIELDS)})
    print(f"{path}: {len(rows)} answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
