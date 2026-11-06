"""Choose between an adapter's saved checkpoints and a smaller LoRA scale, instead of retraining.

    python training/sweep_checkpoints.py medicine --llama-cpp ~/src/llama.cpp \
        --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf \
        [--candidate 0.125 --candidate 0.25 --candidate 0.5 --candidate 1@0.5] \
        [--python CONVERTER_PY] [--base Qwen/Qwen3.5-4B] [--no-final]

A candidate is FRACTION[@SCALE]: the saved checkpoint (training/runs/<id>/adapter/<iteration>_adapters.safetensors)
nearest to FRACTION x the planned iterations of run.json (a tie takes the earlier one; FRACTION 1 is the final
adapters.safetensors), with its LoRA output multiplied by SCALE (default 1). Without --candidate: 0.125, 0.25, 0.5
and 1@0.5. Two candidates with the same iteration and scale are one.

1. Each candidate is exported (training/export_adapter.py) to training/runs/<id>/sweep/gguf/spike-<id>-it<N>-s<S>.gguf;
   the scale is applied there (adapter_config.json's lora_parameters.scale x SCALE, so the GGUF's alpha is
   scale x SCALE x rank), never at runtime. The run's own export.json and ~/.spike/adapters are not touched.
2. One run_eval.py run answers the recipe's acceptance rule with every suite renamed X -> X-select (medicine-select,
   general-select: disjoint from the acceptance samples) for the base model and every candidate.
3. The chosen candidate is the one that passes that rule with the largest gain on the primary suite (a tie takes the
   earlier checkpoint, then the smaller scale). Every candidate tried, passing or not, is in sweep/summary.json.
4. Unless --no-final, the acceptance suites (medicine,general) run once, on the chosen candidate alone, with
   --acceptance training/configs/<id>.yaml: that verdict is the round's verdict.

Exit code 0: accepted (with --no-final: a candidate was chosen); 2: rejected, or no candidate passed the selection;
1: an error. Interrupted: run the same command again, it keeps every finished export and every finished group of
answers. It prints the install command when accepted. Every number comes from the run_eval.py summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train.evaluation import check_acceptance, eval_args  # noqa: E402

DEFAULT_CANDIDATES = ["0.125", "0.25", "0.5", "1@0.5"]
CHECKPOINT = re.compile(r"^(\d+)_adapters\.safetensors$")  # mlx-lm: f"{it:07d}_adapters.safetensors"


@dataclass
class Candidate:
    stem: str
    folder: str  # it<N>-s<S>, under sweep/
    fraction: Fraction
    scale: Fraction
    iteration: int
    checkpoint: Path
    asked: list[str] = field(default_factory=list)  # the --candidate values that resolved to this one


def compact(x: Fraction) -> str:
    """0.5 -> '0.5', 1 -> '1': the shortest text that gives the same number back (a valid file name part)."""
    text = repr(float(x))
    return text[:-2] if text.endswith(".0") else text


def run(cmd: list[str]) -> int:
    return subprocess.run(cmd).returncode


def shown(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()  # the same record on every OS
    except ValueError:
        return str(path)


def file_hash(path: Path) -> str:
    """Hash in bounded chunks: the base GGUF must not be loaded into RAM."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_inputs(sweep: Path, record: dict) -> None:
    sweep.mkdir(parents=True, exist_ok=True)
    path = sweep / "inputs.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def pin_inputs(sweep: Path, candidates: list[Candidate], files: dict[str, Path], base: str | None) -> dict:
    """Bind cached work to its inputs before exporting or reusing predictions.

    New candidates may be added to an interrupted selection. Existing candidates and
    shared inputs cannot change in place: doing so would mix experiments (or give a
    different adapter another look at the acceptance set). Old results without this
    receipt are retained but cannot be attributed to today's files retroactively.
    """
    shared = {"files": {key: file_hash(path) for key, path in files.items()}, "export_base": base}
    current = {c.stem: {"checkpoint_sha256": file_hash(c.checkpoint), "scale": str(c.scale)} for c in candidates}
    path = sweep / "inputs.json"
    record = {"format": "spike-sweep-inputs-v1", "shared": shared, "candidates": {}, "exports": {}}

    def refuse(reason: str) -> None:
        raise SystemExit(f"sweep provenance: {reason}. Existing evidence was not changed. Keep this sweep with its "
                         "original inputs; use a separately documented experiment for changed inputs, never "
                         "retroactively approve them with these results.")

    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            refuse(f"cannot read {shown(path)}")
        if (not isinstance(saved, dict) or saved.get("format") != record["format"]
                or not isinstance(saved.get("candidates"), dict) or not isinstance(saved.get("exports"), dict)):
            refuse(f"invalid {shown(path)}")
        if saved.get("shared") != shared:
            refuse("model, recipe, run, configuration or evaluation inputs changed")
        for stem, identity in current.items():
            if stem in saved["candidates"] and saved["candidates"][stem] != identity:
                refuse(f"checkpoint or scale changed for {stem}")
        # Check all existing exports before any subprocess can overwrite a file.
        for stem, checksum in saved["exports"].items():
            if Path(stem).name != stem:
                refuse("invalid export name")
            gguf = sweep / "gguf" / f"{stem}.gguf"
            if gguf.is_file() and file_hash(gguf) != checksum:
                refuse(f"exported GGUF changed for {stem}")
        record = saved
    elif sweep.exists() and any(p.is_file() and p.name != "inputs.json.tmp" for p in sweep.rglob("*")):
        refuse("cached work has no input receipt; its provenance cannot be established")
    record["candidates"].update(current)
    save_inputs(sweep, record)
    return record


def parse_candidate(text: str) -> tuple[Fraction, Fraction]:
    head, at, tail = text.partition("@")
    try:
        fraction, scale = Fraction(head.strip()), Fraction(tail.strip()) if at else Fraction(1)
    except (ValueError, ZeroDivisionError):
        raise SystemExit(f"bad --candidate '{text}': expected FRACTION[@SCALE], e.g. 0.25 or 1@0.5") from None
    if not 0 < fraction <= 1:
        raise SystemExit(f"bad --candidate '{text}': FRACTION must be above 0 and at most 1")
    if not 0 < scale <= 1:
        raise SystemExit(f"bad --candidate '{text}': SCALE must be above 0 and at most 1")
    return fraction, scale


def list_checkpoints(adapter_dir: Path) -> dict[int, Path]:
    if not adapter_dir.is_dir():
        raise SystemExit(f"no adapter folder at {adapter_dir}: train first (training/scripts/train_supervised.sh)")
    found = {int(m.group(1)): p for p in adapter_dir.iterdir() if (m := CHECKPOINT.match(p.name))}
    if not found:
        raise SystemExit(f"{adapter_dir} has no <iteration>_adapters.safetensors checkpoints "
                         "(mlx-lm saves one every save_every iterations)")
    return found


def plan(specs: list[str], specialist: str, adapter_dir: Path, total: int, finished: bool = True,
         started: float | None = None) -> list[Candidate]:
    """The candidates the --candidate values stand for, in order, without repeats. `finished`: the training run ended
    (run.json's exit_code), so adapters.safetensors is the weights of iteration `total`. `started` (when the run began,
    epoch seconds): a file written before it was left by an earlier, aborted run in the same folder."""
    checkpoints = list_checkpoints(adapter_dir)
    final = adapter_dir / "adapters.safetensors"
    out: dict[tuple[int, Fraction], Candidate] = {}
    for text in specs:
        fraction, scale = parse_candidate(text)
        if fraction == 1:
            if not final.is_file():
                raise SystemExit(f"--candidate '{text}' is the final adapter, but {final} does not exist")
            if not finished:
                raise SystemExit(f"--candidate '{text}' is the final adapter, but run.json records a training run that "
                                 f"did not finish, so {final.name} is not iteration {total}")
            iteration, checkpoint = total, final
        else:  # exact arithmetic: a tie is a tie. min() with the iteration in the key takes the earlier one
            iteration = min(checkpoints, key=lambda it: (abs(it - fraction * total), it))
            checkpoint = checkpoints[iteration]
        if started is not None and checkpoint.stat().st_mtime < started:
            raise SystemExit(f"{checkpoint} was written before the recorded run started (run.json): it is "
                             "from an earlier run in the same folder, not a checkpoint of this one")
        if (iteration, scale) in out:
            out[iteration, scale].asked.append(text)
            continue
        folder = f"it{iteration}-s{compact(scale)}"
        stem = f"spike-{specialist}-{folder}"
        out[iteration, scale] = Candidate(stem, folder, fraction, scale, iteration, checkpoint, [text])
    return list(out.values())


def load_run(specialist: str) -> dict:
    """What the training run recorded: the planned iterations (the last checkpoint is rarely a multiple of the
    save interval) and the commit. mlx_lora.yaml has the iterations too, for a record without counts."""
    path = ROOT / "training" / "runs" / specialist / "run.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found: the sweep reads the planned iterations and the commit from the run record")
    record = json.loads(path.read_text(encoding="utf-8"))
    iters = (record.get("counts") or {}).get("iters")
    if not iters:
        mlx = ROOT / "training" / "data" / specialist / "mlx_lora.yaml"
        iters = yaml.safe_load(mlx.read_text(encoding="utf-8")).get("iters") if mlx.is_file() else None
    if not isinstance(iters, int) or iters <= 0:
        raise SystemExit(f"cannot tell how many iterations were planned: {path} has no counts.iters "
                         f"and training/data/{specialist}/mlx_lora.yaml has no iters")
    # run_started_utc (train.sh): when the run began, across the RAM guard's resumed attempts, each of which rewrites
    # started_utc; a resumed attempt that cannot tell records None, and older records (one attempt each) lack the key
    started = record["run_started_utc"] if "run_started_utc" in record else record.get("started_utc")
    return {"git_commit": record.get("git_commit"), "iters": iters, "exit_code": record.get("exit_code"),
            "started_utc": started}


def rule_suites(acceptance: dict) -> list[str]:
    return list(dict.fromkeys(acceptance[k]["suite"] for k in ("primary", "regression") if acceptance.get(k)))


def select_rule(acceptance: dict, suites: dict) -> dict:
    """The recipe's own acceptance rule with every suite renamed X -> X-select."""
    if "min_gain_points" not in (acceptance.get("primary") or {}):
        raise SystemExit("the recipe is not judged by exact-answer suites (primary.min_gain_points): "
                         "the sweep cannot choose with it")
    mapped = dict(acceptance)
    for key in ("primary", "regression"):
        if acceptance.get(key):
            mapped[key] = {**acceptance[key], "suite": acceptance[key]["suite"] + "-select"}
    missing = [name for name in rule_suites(mapped) if name not in suites]
    if missing:
        raise SystemExit(f"evals/suites.yaml has no suite {', '.join(missing)}: choosing needs suites disjoint from "
                         "the acceptance samples (add them with `skip`, as general-select has)")
    return mapped


def write_scaled_adapter(candidate: Candidate, adapter_dir: Path, dest: Path) -> None:
    """An mlx adapter folder for one candidate: the run's adapter_config.json with lora_parameters.scale x SCALE
    (export_adapter.py turns scale x rank into PEFT's alpha) and the checkpoint as adapters.safetensors."""
    config = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    params = config.get("lora_parameters") or {}
    if not isinstance(params.get("scale"), (int, float)):
        raise SystemExit(f"{adapter_dir / 'adapter_config.json'} has no lora_parameters.scale to scale")
    if candidate.scale != 1:
        params["scale"] = params["scale"] * float(candidate.scale)
    config["lora_parameters"] = params
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "adapter_config.json").write_text(json.dumps(config, indent=4), encoding="utf-8")
    link = dest / "adapters.safetensors"
    link.unlink(missing_ok=True)
    link.symlink_to(candidate.checkpoint.resolve())


def export_candidate(candidate: Candidate, sweep: Path, adapter_dir: Path, args: argparse.Namespace,
                     base: str | None, *, reuse: bool = True) -> Path:
    """GGUF of one candidate (skipped when it and its export.json are already there)."""
    work, gguf = sweep / candidate.folder, sweep / "gguf" / f"{candidate.stem}.gguf"
    if reuse and gguf.is_file() and (work / "export.json").is_file():
        print(f"{candidate.stem}: already exported")
        return gguf
    write_scaled_adapter(candidate, adapter_dir, work / "mlx")
    cmd = [sys.executable, str(ROOT / "training" / "export_adapter.py"), args.specialist, "--llama-cpp", args.llama_cpp,
           "--adapter", str(work / "mlx"), "--out", str(gguf.parent), "--name", candidate.stem, "--work", str(work)]
    if base:
        cmd += ["--base", base]
    if args.python:
        cmd += ["--python", args.python]
    print(f"{candidate.stem}: exporting checkpoint {candidate.checkpoint.name} x scale {compact(candidate.scale)}")
    if code := run(cmd):
        raise SystemExit(f"exporting {candidate.stem} failed (exit {code}); run the same command again after fixing it")
    if not gguf.is_file():
        raise SystemExit(f"the export of {candidate.stem} wrote no {gguf}")
    return gguf


def evaluate(out: Path, adapters: list[Path], suites: list[str], model: Path, extra: list[str],
             acceptance: Path | None = None) -> tuple[dict, int | None]:
    """run_eval.py on the base model and `adapters` into `out`, doing only what is missing: results that list exactly
    these adapters (and a verdict, when one is asked for) are reused; an interrupted or smaller run is finished with
    --resume. Returns the summary and run_eval's exit code (None when reused)."""
    stems = {a.stem for a in adapters}
    summary_file, predictions = out / "summary.json", out / "predictions.jsonl"
    if summary_file.is_file():
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        have = set(summary.get("variants") or []) - {"base"}
        if not have <= stems:  # starting over would drop adapters that were tried: they must stay in the report
            raise SystemExit(f"{shown(out)} has results for {', '.join(sorted(have - stems))}, which this run does not "
                             "ask for: ask for the same candidates, or move that folder aside")
        if have == stems and (acceptance is None or stems <= set(summary.get("acceptance") or {})):
            print(f"{shown(out)}: results for {len(stems)} adapter(s) already there, reused")
            return summary, None
    cmd = [sys.executable, str(ROOT / "evals" / "run_eval.py"), "--suites", ",".join(suites), "--model", str(model)]
    for adapter in adapters:
        cmd += ["--adapter", str(adapter)]
    cmd += extra
    if acceptance:
        cmd += ["--acceptance", str(acceptance)]
    cmd += ["--resume", str(out)] if predictions.is_file() else ["--out", str(out)]
    code = run(cmd)
    if code not in ((0, 2) if acceptance else (0,)) or not summary_file.is_file():
        raise SystemExit(f"run_eval.py exited with {code} for {shown(out)}: fix the cause and run the same command "
                         "again, the finished groups of answers are kept")
    return json.loads(summary_file.read_text(encoding="utf-8")), code


def comparison(summary: dict, suite: str, stem: str) -> dict | None:
    cmp = (summary["suites"].get(suite) or {}).get("vs_base", {}).get(stem)
    return None if cmp is None else {"suite": suite, "paired_n": cmp["paired_n"], "delta_points": cmp["delta_points"],
                                     "p_value": cmp["p_value"]}


def judge(candidates: list[Candidate], summary: dict, rule: dict, sweep: Path) -> list[dict]:
    """One record per candidate: where it came from, its measured comparison on the select suites and whether the
    recipe's rule (renamed to the select suites) passes."""
    rows = []
    for c in candidates:
        ok, reasons = check_acceptance(summary, rule, c.stem)
        rows.append({"asked": c.asked, "fraction": float(c.fraction), "iteration": c.iteration, "scale": float(c.scale),
                     "stem": c.stem, "checkpoint": shown(c.checkpoint),
                     "gguf": shown(sweep / "gguf" / f"{c.stem}.gguf"),
                     "select": {key: comparison(summary, rule[key]["suite"], c.stem) if rule.get(key) else None
                                for key in ("primary", "regression")},
                     "passes": ok, "reasons": reasons})
    return rows


def choose(rows: list[dict]) -> dict | None:
    """The passing candidate with the largest primary gain; a tie takes the earlier checkpoint, then the smaller
    scale."""
    passing = [r for r in rows if r["passes"]]
    return max(passing, key=lambda r: (r["select"]["primary"]["delta_points"], -r["iteration"], -r["scale"]),
               default=None)


def render_markdown(summary: dict) -> str:
    primary = summary["select"]["rule"]["primary"]["suite"]
    regression = (summary["select"]["rule"].get("regression") or {}).get("suite")
    run_info = summary["run"]
    lines = [f"# Checkpoint sweep: {summary['specialist']}", "",
             f"Recipe `{summary['recipe']}`, trained at commit `{run_info['git_commit']}` for {run_info['iters']} "
             f"iterations. Chosen on `{', '.join(summary['select']['suites'])}` (the recipe's rule with the suites "
             f"renamed), measured against the base model in one run (`{summary['select']['results']}`).", "",
             f"| candidate | asked | iteration | scale | {primary} Δ pts (p) | {regression or 'regression'} Δ pts "
             "| passes |", "|---|---|---|---|---|---|---|"]
    for r in summary["candidates"]:
        p, g = r["select"]["primary"], r["select"]["regression"]
        lines.append(f"| {r['stem']} | {', '.join(r['asked'])} | {r['iteration']} | {r['scale']:g} | "
                     + (f"{p['delta_points']:+.2f} ({p['p_value']:.4g})" if p else "not evaluated") + " | "
                     + (f"{g['delta_points']:+.2f}" if g else "") + f" | {'yes' if r['passes'] else 'no'} |")
    lines += ["", f"Chosen: `{summary['chosen']}`" if summary["chosen"] else "Chosen: none, no candidate passed."]
    for r in summary["candidates"]:
        lines.append(f"- {r['stem']}: " + "; ".join(r["reasons"]))
    final = summary["final"]
    if final:
        lines += ["", f"**Final, on the acceptance suites ({', '.join(final['suites'])}): "
                      f"{'ACCEPTED' if final['accepted'] else 'REJECTED'}** (`{final['results']}`)",
                  *[f"- {reason}" for reason in final["reasons"]]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Choose between saved checkpoints and a smaller LoRA scale.")
    ap.add_argument("specialist")
    ap.add_argument("--llama-cpp", required=True, help="llama.cpp checkout containing convert_lora_to_gguf.py")
    ap.add_argument("--model", required=True, help="base GGUF the candidates are evaluated on")
    ap.add_argument("--candidate", action="append", metavar="FRACTION[@SCALE]",
                    help=f"repeatable (default {' '.join('--candidate ' + c for c in DEFAULT_CANDIDATES)})")
    ap.add_argument("--base", help="HF repo id or local dir of the training base (default: the recipe's base_model)")
    ap.add_argument("--python", help="interpreter with the converter's requirements (export_adapter.py's default)")
    ap.add_argument("--no-final", action="store_true", help="choose only; do not run the acceptance suites")
    args = ap.parse_args(argv)

    spec = args.specialist
    runs = ROOT / "training" / "runs" / spec
    sweep, adapter_dir = runs / "sweep", runs / "adapter"
    recipe = ROOT / "training" / "configs" / f"{spec}.yaml"
    if not recipe.is_file():
        raise SystemExit(f"no recipe at {recipe}")
    cfg = yaml.safe_load(recipe.read_text(encoding="utf-8"))
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
    rule = select_rule(cfg.get("acceptance") or {}, suites)
    try:
        extra = eval_args(cfg)
    except ValueError as exc:
        raise SystemExit(f"{recipe.name}: {exc}") from None
    run_info = load_run(spec)
    finished = run_info.pop("exit_code") in (None, 0)
    started = (datetime.strptime(run_info["started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
               if run_info.get("started_utc") else None)
    candidates = plan(args.candidate or DEFAULT_CANDIDATES, spec, adapter_dir, run_info["iters"], finished, started)
    model = Path(args.model).expanduser()
    if not model.is_file():
        raise SystemExit(f"base model not found: {model}")
    if not (Path(args.llama_cpp).expanduser() / "convert_lora_to_gguf.py").is_file():
        raise SystemExit(f"{args.llama_cpp} has no convert_lora_to_gguf.py: pass the llama.cpp checkout")
    args.llama_cpp = str(Path(args.llama_cpp).expanduser())

    base = args.base or cfg.get("base_model")
    inputs = {"model": model, "recipe": recipe, "run": runs / "run.json",
              "adapter_config": adapter_dir / "adapter_config.json", "suites": ROOT / "evals" / "suites.yaml",
              "converter": Path(args.llama_cpp) / "convert_lora_to_gguf.py"}
    for relative in (f"training/data/{spec}/mlx_lora.yaml", "training/datasets.yaml",
                     "spike/specialists/catalog.yaml", "evals/run_eval.py",
                     "training/export_adapter.py", "training/spike_train/evaluation.py",
                     "training/spike_train/metrics.py"):
        if (source := ROOT / relative).is_file():
            inputs[relative] = source
    if base and Path(base).expanduser().is_dir():
        for source in Path(base).expanduser().glob("*.json"):
            inputs[f"base_config/{source.name}"] = source
    provenance = pin_inputs(sweep, candidates, inputs, base)
    ggufs = []
    for candidate in candidates:
        gguf = export_candidate(candidate, sweep, adapter_dir, args, base,
                                reuse=candidate.stem in provenance["exports"])
        checksum = file_hash(gguf)
        old = provenance["exports"].get(candidate.stem)
        if old is not None and old != checksum:
            raise SystemExit(f"sweep provenance: regenerated GGUF changed for {candidate.stem}; "
                             "old predictions were not reused")
        provenance["exports"][candidate.stem] = checksum
        save_inputs(sweep, provenance)
        ggufs.append(gguf)
    select_suites = rule_suites(rule)
    summary, _ = evaluate(sweep / "select", ggufs, select_suites, model, extra)
    rows = judge(candidates, summary, rule, sweep)
    for r in rows:
        print(f"{r['stem']}: {'passes' if r['passes'] else 'fails'} the select rule; " + "; ".join(r["reasons"]))
    best = choose(rows)

    final = None
    if best and not args.no_final:
        gguf = sweep / "gguf" / f"{best['stem']}.gguf"
        final_suites = rule_suites(cfg["acceptance"])
        results, code = evaluate(sweep / "final", [gguf], final_suites, model, extra, recipe)
        verdict = results["acceptance"][best["stem"]]
        accepted = bool(verdict["accepted"])
        final = {"suites": final_suites, "results": shown(sweep / "final"), "accepted": accepted,
                 "reasons": verdict["reasons"], "exit_code": (0 if accepted else 2) if code is None else code,
                 "reused": code is None}
    exit_code = 2 if best is None or (final and not final["accepted"]) else 0

    out = {"specialist": spec, "recipe": shown(recipe), "run": run_info, "model": str(model),
           "select": {"suites": select_suites, "rule": rule, "results": shown(sweep / "select")},
           "candidates": rows, "chosen": best["stem"] if best else None, "final": final, "exit_code": exit_code}
    (sweep / "summary.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (sweep / "summary.md").write_text(render_markdown(out), encoding="utf-8")
    print(f"\nsummary: {shown(sweep / 'summary.json')}")

    if best is None:
        print("no candidate passes the select rule, so the acceptance suites were not run: not accepted")
    elif final is None:
        print(f"chosen: {best['stem']}. Run the same command without --no-final to run the acceptance suites on it")
    elif final["accepted"]:
        print(f"ACCEPTED: {best['stem']} passes the acceptance suites. Install it (from the repo root):\n"
              f"  spike adapters install {best['gguf']} --specialist {spec} --eval {final['results']} "
              f"--config {shown(recipe)}")
    else:
        print(f"REJECTED: {best['stem']} fails the acceptance suites ({'; '.join(final['reasons'])}); "
              f"{spec} stays a prompt profile")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
