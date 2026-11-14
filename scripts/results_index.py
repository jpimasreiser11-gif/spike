"""Build docs/results/specialists.json: every specialist's measured results, from the evidence committed in this
repository and nothing else (the Mando benchmark tab and anyone else read this one file).

    python scripts/results_index.py          # write it
    python scripts/results_index.py --check  # fail if it is out of date (CI)

Sources: each round's sweep `training/runs/<id>/**/summary.json` (written by training/sweep_checkpoints.py), the
`run_eval.py` summaries it points to, `questions.jsonl` beside them when evals/export_questions.py has been run, the
accepted adapter record `spike/specialists/acceptance/<id>.json`, and evals/suites.yaml + training/datasets.yaml for
what each test is. A specialist with no committed round answers as an instruction profile on the base model.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "results" / "specialists.json"
FORMAT = "spike-specialist-results-v1"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def specialists() -> list[str]:
    data = yaml.safe_load((ROOT / "spike/specialists/catalog.yaml").read_text(encoding="utf-8"))
    return [s["id"] for s in data["specialists"] if s["id"] != "core"]


def benchmarks() -> dict[str, dict]:
    """Every eval task: which public test it samples and how."""
    registry = yaml.safe_load((ROOT / "training/datasets.yaml").read_text(encoding="utf-8"))["sources"]
    suites = yaml.safe_load((ROOT / "evals/suites.yaml").read_text(encoding="utf-8"))["suites"]
    out: dict[str, dict] = {}
    for suite_name, suite in suites.items():
        for task in suite["tasks"]:
            src = registry.get(task.get("source"), {})
            out[task["name"]] = {
                "suite": suite_name,
                "dataset": src.get("hub") or src.get("file") or task.get("source"),
                "config": src.get("config"),
                "split": src.get("split"),
                "license": src.get("license"),
                "categories": task.get("categories"),
                "sample": task.get("n"),
                "skip": task.get("skip", 0),
            }
    return out


def protocol(meta: dict) -> dict:
    return {"model": Path(str(meta.get("model") or "")).name or None, "llama_cpp": meta.get("props"),
            "decoding": meta.get("decoding"), "thinking": meta.get("thinking"), "max_tokens": meta.get("max_tokens"),
            "seed": meta.get("seed"), "kv_cache_type": meta.get("kv_cache_type"),
            "prompt": "the specialist's system prompt; zero-shot (question, options, answer-format instruction)"}


def score(acc: dict) -> dict:
    return {k: acc.get(k) for k in ("n", "correct", "accuracy", "ci95", "unparsed", "truncated")}


def topics(run_dir: Path, variant: str) -> tuple[str | None, dict]:
    """Per task and topic: n, base_correct, adapter_correct, from questions.jsonl (None when not exported)."""
    path = run_dir / "questions.jsonl"
    if not path.is_file():
        return None, {}
    table: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "base_correct": 0,
                                                                                 "adapter_correct": 0}))
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["variant"] not in ("base", variant):
            continue
        cell = table[r["task"]][r["topic"]]
        if r["variant"] == "base":
            cell["n"] += 1
            cell["base_correct"] += int(r["correct"])
        else:
            cell["adapter_correct"] += int(r["correct"])
    return rel(path), {task: dict(sorted(by_topic.items())) for task, by_topic in sorted(table.items())}


def results_dir(stated: str | None, sweep_dir: Path) -> Path | None:
    """The folder a sweep's summary names, or the same name inside the sweep's own folder (an archived round keeps
    the paths it had before training/fix_forgetting.py moved it to round<N>/)."""
    if not stated:
        return None
    for candidate in (ROOT / stated, sweep_dir / Path(stated).name):
        if (candidate / "summary.json").is_file():
            return candidate
    return None


def final_result(sweep: dict, chosen: str, sweep_dir: Path) -> dict | None:
    run_dir = results_dir((sweep.get("final") or {}).get("results"), sweep_dir)
    if run_dir is None:
        return None
    summary = load(run_dir / "summary.json")
    if "win_rate" in summary:  # evals/pairwise.py: judged against the base model, not scored against a key
        keys = ("n", "wins", "losses", "ties", "win_rate", "sign_test_p", "judge", "caveat", "prompts", "general")
        return {"evidence": rel(run_dir / "summary.json"), "pairwise": {k: summary.get(k) for k in keys}}
    tasks = {}
    for name, task in summary.get("tasks", {}).items():
        acc, vs = task.get("accuracy", {}), task.get("vs_base", {}).get(chosen, {})
        tasks[name] = {"base": score(acc.get("base", {})), "adapter": score(acc.get(chosen, {})),
                       "delta_points": vs.get("delta_points"), "p_value": vs.get("p_value")}
    suites = {}
    for name, suite in summary.get("suites", {}).items():
        acc, vs = suite.get("accuracy", {}), suite.get("vs_base", {}).get(chosen, {})
        suites[name] = {"base": score(acc.get("base", {})), "adapter": score(acc.get(chosen, {})),
                        "delta_points": vs.get("delta_points"), "p_value": vs.get("p_value")}
    questions, by_topic = topics(run_dir, chosen)
    return {"evidence": rel(run_dir / "summary.json"), "protocol": protocol(summary.get("meta", {})),
            "suites": suites, "tasks": tasks, "questions": questions, "topics": by_topic}


def candidate(c: dict) -> dict:
    sel = c.get("select") or {}
    return {"name": c.get("stem"), "iteration": c.get("iteration"), "scale": c.get("scale"),
            "select": {side: {k: v for k, v in (sel.get(side) or {}).items()} for side in ("primary", "regression")
                       if sel.get(side)},
            "passes": c.get("passes"), "reasons": c.get("reasons", [])}


def round_of(path: Path, specialist: str) -> dict:
    sweep = load(path)
    base = ROOT / "training/runs" / specialist
    run_json = path.parent.parent / "run.json"
    run = load(run_json) if run_json.is_file() else {}
    chosen = sweep.get("chosen")
    final = sweep.get("final") or {}
    if chosen is None:
        verdict, reasons = "rejected", ["no candidate passed the selection"]
    elif "accepted" in final:
        verdict, reasons = ("accepted" if final["accepted"] else "rejected"), final.get("reasons", [])
    else:
        verdict, reasons = "chosen_not_final", ["the chosen candidate has no final evaluation yet"]
    return {
        "sweep": path.parent.relative_to(base).as_posix(),
        "evidence": rel(path),
        "trained_utc": {"started": run.get("run_started_utc") or run.get("started_utc") or
                        (sweep.get("run") or {}).get("started_utc"), "finished": run.get("finished_utc")},
        "git_commit": (sweep.get("run") or {}).get("git_commit"),
        "data": {k: (run.get("counts") or {}).get(k) for k in ("train", "valid", "replay_ratio_actual")} if run else None,
        "rule": (sweep.get("select") or {}).get("rule"),
        "candidates": [candidate(c) for c in sweep.get("candidates", [])],
        "chosen": chosen,
        "verdict": verdict,
        "reasons": reasons,
        "final": final_result(sweep, chosen, path.parent) if chosen else None,
    }


def build() -> dict:
    out = {"format": FORMAT,
           "about": "Measured results only, from files committed in this repository; regenerate with "
                    "scripts/results_index.py. delta_points = adapter minus base on the same questions; "
                    "unparsed = answers the extractor could not read (scored wrong).",
           "base_model": "Qwen3.5-4B Q4_K_M (llama.cpp)",
           "benchmarks": benchmarks(), "specialists": {}}
    for sid in specialists():
        rounds = []
        runs = ROOT / "training/runs" / sid
        for path in sorted(runs.rglob("summary.json")) if runs.is_dir() else []:
            try:
                data = load(path)
            except ValueError:
                continue
            if data.get("specialist") == sid and "candidates" in data:
                rounds.append(round_of(path, sid))
        rounds.sort(key=lambda r: (r["trained_utc"]["started"] or "", r["sweep"]))
        starts = list(dict.fromkeys(r["trained_utc"]["started"] for r in rounds))  # two sweeps of one run: one round
        rounds = [{"round": starts.index(r["trained_utc"]["started"]) + 1, **r} for r in rounds]
        record = ROOT / "spike/specialists/acceptance" / f"{sid}.json"
        accepted = load(record) if record.is_file() else None
        if accepted:
            accepted = {k: accepted.get(k) for k in ("evaluated_as", "date", "file", "sha256", "reasons", "evidence")}
        out["specialists"][sid] = {
            "status": "adapter_accepted" if accepted else "base_profile",
            "accepted": accepted,
            "rounds": rounds,
        }
    return out


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if docs/results/specialists.json is out of date")
    args = ap.parse_args(argv)
    text = render(build())
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.name} is out of date: run python scripts/results_index.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
