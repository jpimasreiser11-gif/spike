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

A recipe judged by a pairwise win rate (primary.min_win_rate, e.g. marketing) is chosen the same way, with its own
selection suite: evals/pairwise.py compares every candidate with the base model on at most 48 teacher-written tasks of
the run's own valid split (never trained on, decontaminated against the acceptance prompts, a seeded sample written to
sweep/select-prompts.jsonl), judged in both orders by --judge-model at --judge-url, together with general-select. The
chosen candidate is the passing one with the highest win rate (a tie: the earlier checkpoint, then the smaller scale).
The final verdict is the general suite and evals/pairwise.py on the recipe's acceptance prompts (primary.prompts), once,
on the chosen candidate. Answers come first and are kept: when the judge cannot be reached the sweep stops with exit
code 3; start the judge and run the same command again.

Exit code 0: accepted (with --no-final: a candidate was chosen); 2: rejected, or no candidate passed the selection;
3: waiting for the judge (pairwise recipes); 1: an error. Interrupted: run the same command again, it keeps every
finished export and every finished group of answers. It prints the install command when accepted. Every number comes
from the run_eval.py and pairwise.py summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
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

from spike_train.evaluation import check_acceptance, check_pairwise_acceptance, eval_args  # noqa: E402

DEFAULT_CANDIDATES = ["0.125", "0.25", "0.5", "1@0.5"]
SELECT_PROMPTS = 48  # teacher-written tasks of the valid split a pairwise recipe is chosen on
WAITING_FOR_JUDGE = 3  # evals/pairwise.py: the answers are kept, the judge did not answer
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


def pin_inputs(sweep: Path, candidates: list[Candidate], files: dict[str, Path], base: str | None,
               settings: dict | None = None) -> dict:
    """Bind cached work to its inputs before exporting or reusing predictions.

    New candidates may be added to an interrupted selection. Existing candidates and
    shared inputs cannot change in place: doing so would mix experiments (or give a
    different adapter another look at the acceptance set). Old results without this
    receipt are retained but cannot be attributed to today's files retroactively.
    """
    shared = {"files": {key: file_hash(path) for key, path in files.items()}, "export_base": base}
    if settings:  # pairwise recipes only: the judge (exact-answer sweeps keep the record they always had)
        shared["settings"] = settings
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


def is_pairwise(acceptance: dict) -> bool:
    return "min_win_rate" in (acceptance.get("primary") or {})


def select_rule(acceptance: dict, suites: dict) -> dict:
    """The recipe's own acceptance rule with every suite renamed X -> X-select. A pairwise recipe's primary select
    suite is not in evals/suites.yaml: it is made from the run's valid split (selection_prompts)."""
    primary = acceptance.get("primary") or {}
    pairwise = is_pairwise(acceptance)
    if not pairwise and "min_gain_points" not in primary:
        raise SystemExit("the recipe has neither an exact-answer rule (primary.min_gain_points) nor a pairwise one "
                         "(primary.min_win_rate): the sweep cannot choose with it")
    mapped = dict(acceptance)
    for key in ("primary", "regression"):
        if acceptance.get(key):
            mapped[key] = {**acceptance[key], "suite": acceptance[key]["suite"] + "-select"}
    if pairwise:
        mapped["primary"].pop("prompts", None)  # the acceptance prompts are never used to choose
    missing = [name for name in rule_suites(mapped) if name not in suites
               and not (pairwise and name == mapped["primary"]["suite"])]
    if missing:
        raise SystemExit(f"evals/suites.yaml has no suite {', '.join(missing)}: choosing needs suites disjoint from "
                         "the acceptance samples (add them with `skip`, as general-select has)")
    return mapped


def first_user(chat: dict) -> str | None:
    return next((m.get("content") for m in chat.get("messages") or [] if m.get("role") == "user"), None)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def selection_prompts(data: Path, distilled: Path, run_files: dict, seed: int) -> list[dict]:
    """The prompts a pairwise recipe is chosen on: at most SELECT_PROMPTS teacher-written tasks of the run's own valid
    split, a seeded sample. A valid row is one when its request is a task of `distilled` (the teacher's file
    prepare.py read, by its recorded hash) and not also in train.jsonl; prepare.py already dropped every row close to
    the acceptance prompts (decontaminate_files)."""
    valid, train, manifest_file = data / "valid.jsonl", data / "train.jsonl", data / "manifest.json"
    for path in (valid, train, manifest_file, distilled):
        if not path.is_file():
            raise SystemExit(f"{shown(path)} not found: a pairwise recipe is chosen on the teacher-written tasks of the "
                             "run's valid split (pass the teacher's file with --select-from)")
    for name, path in (("valid.jsonl", valid), ("train.jsonl", train)):
        if run_files.get(name) != file_hash(path):
            raise SystemExit(f"{shown(path)} is not the file the training run used (run.json data_files_sha256): "
                             "the selection prompts must come from the run's own valid split")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("files") or {}).get("valid.jsonl") != run_files.get("valid.jsonl"):
        raise SystemExit(f"{shown(manifest_file)} does not describe the run's data (its files differ from run.json)")
    record = (manifest.get("sources") or {}).get(f"distilled:{distilled.name}")
    if not record:
        raise SystemExit(f"the run's data was not prepared from {distilled.name} (no distilled:{distilled.name} in "
                         f"{shown(manifest_file)}): pass the teacher's file prepare.py read with --select-from")
    if record.get("sha256") != file_hash(distilled):
        raise SystemExit(f"{shown(distilled)} is not the file prepare.py read (its hash differs from the one in "
                         f"{shown(manifest_file)}, or none was recorded): the teacher's tasks cannot be told apart")
    tasks = {}
    for chat in jsonl(distilled):
        if text := first_user(chat):
            tasks.setdefault(text, (chat.get("meta") or {}).get("task_id"))
    trained = {first_user(chat) for chat in jsonl(train)}
    rows, seen = [], set()
    for n, chat in enumerate(jsonl(valid), 1):
        text = first_user(chat)
        if text in tasks and text not in trained and text not in seen:
            seen.add(text)
            rows.append({"id": f"valid-{n}", "prompt": text, **({"task_id": tasks[text]} if tasks[text] else {})})
    if not rows:
        raise SystemExit(f"{shown(valid)} has no teacher-written task to choose on")
    picked = sorted(random.Random(seed).sample(range(len(rows)), min(SELECT_PROMPTS, len(rows))))
    return [rows[i] for i in picked]


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


def compare(out: Path, adapters: list[Path], prompts: Path, model: Path, extra: list[str], args: argparse.Namespace,
            acceptance: Path | None = None, general: Path | None = None) -> tuple[dict | None, int]:
    """evals/pairwise.py: the base model against `adapters` on `prompts`, in `out`; it does only what is missing there.
    Returns its summary and exit code, or None and WAITING_FOR_JUDGE when the judge cannot be reached (the answers
    are kept)."""
    cmd = [sys.executable, str(ROOT / "evals" / "pairwise.py"), "--specialist", args.specialist,
           "--prompts", str(prompts), "--model", str(model)]
    for adapter in adapters:
        cmd += ["--adapter", str(adapter)]
    cmd += ["--judge-url", args.judge_url, "--judge-model", args.judge_model, *extra, "--out", str(out)]
    if acceptance:
        cmd += ["--acceptance", str(acceptance)]
        if general:
            cmd += ["--general-eval", str(general)]
    code = run(cmd)
    if code == WAITING_FOR_JUDGE:
        return None, code
    if code not in ((0, 2) if acceptance else (0,)) or not (out / "summary.json").is_file():
        raise SystemExit(f"evals/pairwise.py exited with {code} for {shown(out)}: fix the cause and run the same "
                         "command again, the finished answers and judgments are kept")
    return json.loads((out / "summary.json").read_text(encoding="utf-8")), code


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


PAIRWISE_KEYS = ("n", "wins", "losses", "ties", "win_rate", "sign_test_p")


def judge_pairwise(candidates: list[Candidate], pairs: dict, general: dict | None, rule: dict,
                   sweep: Path) -> list[dict]:
    """judge() for a pairwise recipe: each candidate's win rate on the selection prompts (evals/pairwise.py) and its
    general-select comparison, under the recipe's rule renamed to the select suites."""
    results = pairs["adapters"] if "adapters" in pairs else {pairs["adapter"]: pairs}  # one adapter: flat summary
    regression = rule.get("regression")
    rows = []
    for c in candidates:
        res = results.get(c.stem)
        primary = {"suite": rule["primary"]["suite"], **{k: res[k] for k in PAIRWISE_KEYS}} if res else None
        general_cmp = comparison(general, regression["suite"], c.stem) if regression and general else None
        if res is None:
            ok, reasons = False, [f"{rule['primary']['suite']} was not judged for {c.stem}"]
        else:
            ok, reasons = check_pairwise_acceptance(
                {**res, "adapter": c.stem, **({"general": general_cmp} if general_cmp else {})}, rule)
        rows.append({"asked": c.asked, "fraction": float(c.fraction), "iteration": c.iteration, "scale": float(c.scale),
                     "stem": c.stem, "checkpoint": shown(c.checkpoint),
                     "gguf": shown(sweep / "gguf" / f"{c.stem}.gguf"),
                     "select": {"primary": primary, "regression": general_cmp},
                     "passes": ok, "reasons": reasons})
    return rows


def choose(rows: list[dict]) -> dict | None:
    """The passing candidate with the largest primary gain (a pairwise recipe: the highest win rate); a tie takes the
    earlier checkpoint, then the smaller scale."""
    def gain(r: dict) -> float:
        primary = r["select"]["primary"]
        return primary["win_rate"] if "win_rate" in primary else primary["delta_points"]

    passing = [r for r in rows if r["passes"]]
    return max(passing, key=lambda r: (gain(r), -r["iteration"], -r["scale"]), default=None)


def render_markdown(summary: dict) -> str:
    primary = summary["select"]["rule"]["primary"]["suite"]
    regression = (summary["select"]["rule"].get("regression") or {}).get("suite")
    run_info = summary["run"]
    pairwise = "min_win_rate" in summary["select"]["rule"]["primary"]
    measure = "win rate (sign test p)" if pairwise else "Δ pts (p)"
    lines = [f"# Checkpoint sweep: {summary['specialist']}", "",
             f"Recipe `{summary['recipe']}`, trained at commit `{run_info['git_commit']}` for {run_info['iters']} "
             f"iterations. Chosen on `{', '.join(summary['select']['suites'])}` (the recipe's rule with the suites "
             f"renamed), measured against the base model in one run (`{summary['select']['results']}`).", "",
             *([f"Pairwise selection: {summary['select']['prompts']['n']} teacher-written tasks of the run's valid split "
                f"(`{summary['select']['prompts']['file']}`), judged by `{summary['select']['judge']}` in both orders.",
                ""] if pairwise else []),
             f"| candidate | asked | iteration | scale | {primary} {measure} | {regression or 'regression'} Δ pts "
             "| passes |", "|---|---|---|---|---|---|---|"]
    for r in summary["candidates"]:
        p, g = r["select"]["primary"], r["select"]["regression"]
        lines.append(f"| {r['stem']} | {', '.join(r['asked'])} | {r['iteration']} | {r['scale']:g} | "
                     + ("not evaluated" if not p else f"{p['win_rate']:.3f} ({p['sign_test_p']:.4g})" if pairwise
                        else f"{p['delta_points']:+.2f} ({p['p_value']:.4g})") + " | "
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


def waiting(folder: Path, args: argparse.Namespace) -> int:
    print(f"the answers are kept in {shown(folder)}; the judge does not answer at {args.judge_url}. Start it "
          f"(mlx_lm.server --model {args.judge_model} --port 8090) and run the same command again.")
    return WAITING_FOR_JUDGE


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
    ap.add_argument("--judge-url", default="http://127.0.0.1:8090/v1", help="pairwise recipes: the judge's endpoint")
    ap.add_argument("--judge-model", default="mlx-community/Qwen3.6-35B-A3B-4bit", help="pairwise recipes: the judge")
    ap.add_argument("--select-from", metavar="DISTILLED_JSONL",
                    help="pairwise recipes: the teacher's file prepare.py read (default "
                         "training/data/<specialist>/distilled.jsonl)")
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
    pairwise, settings = is_pairwise(cfg["acceptance"]), None
    if pairwise:  # everything the selection and the verdict read, before hours of work
        data = ROOT / "training" / "data" / spec
        distilled = Path(args.select_from).expanduser() if args.select_from else data / "distilled.jsonl"
        record = json.loads((runs / "run.json").read_text(encoding="utf-8"))
        prompts = selection_prompts(data, distilled, record.get("data_files_sha256") or {}, cfg.get("seed", 0))
        accept_prompts = ROOT / str(cfg["acceptance"]["primary"].get("prompts") or "")
        if not cfg["acceptance"]["primary"].get("prompts") or not accept_prompts.is_file():
            raise SystemExit(f"{recipe.name}: acceptance.primary.prompts must name the held-out prompts file of the "
                             "final pairwise verdict (e.g. evals/data/marketing_eval.jsonl)")
        inputs |= {"evals/pairwise.py": ROOT / "evals" / "pairwise.py", "valid": data / "valid.jsonl",
                   "train": data / "train.jsonl", "manifest": data / "manifest.json", "distilled": distilled,
                   "acceptance_prompts": accept_prompts}
        settings = {"judge": args.judge_model, "select_prompts": SELECT_PROMPTS}
    provenance = pin_inputs(sweep, candidates, inputs, base, settings)
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
    select_record: dict = {"suites": select_suites, "rule": rule, "results": shown(sweep / "select")}
    if pairwise:
        regression = (rule.get("regression") or {}).get("suite")
        general = evaluate(sweep / "select", ggufs, [regression], model, extra)[0] if regression else None
        prompts_file = sweep / "select-prompts.jsonl"
        prompts_file.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts), encoding="utf-8")
        pairs, code = compare(sweep / "select-pairwise", ggufs, prompts_file, model, extra, args)
        if pairs is None:
            return waiting(sweep / "select-pairwise", args)
        rows = judge_pairwise(candidates, pairs, general, rule, sweep)
        select_record |= {"pairwise": shown(sweep / "select-pairwise"), "judge": args.judge_model,
                          "prompts": {"file": shown(prompts_file), "n": len(prompts)}}
    else:
        summary, _ = evaluate(sweep / "select", ggufs, select_suites, model, extra)
        rows = judge(candidates, summary, rule, sweep)
    for r in rows:
        print(f"{r['stem']}: {'passes' if r['passes'] else 'fails'} the select rule; " + "; ".join(r["reasons"]))
    best = choose(rows)

    final = None
    if best and not args.no_final and pairwise:
        gguf = sweep / "gguf" / f"{best['stem']}.gguf"
        final_suites = rule_suites(cfg["acceptance"])
        regression = (cfg["acceptance"].get("regression") or {}).get("suite")
        if regression:  # the general suite first: it needs no judge
            evaluate(sweep / "final-general", [gguf], [regression], model, extra)
        reused = "accepted" in (json.loads((sweep / "final" / "summary.json").read_text(encoding="utf-8"))
                                if (sweep / "final" / "summary.json").is_file() else {})
        results, code = compare(sweep / "final", [gguf], accept_prompts, model, extra, args, recipe,
                                sweep / "final-general" if regression else None)
        if results is None:
            return waiting(sweep / "final", args)
        final = {"suites": final_suites, "results": shown(sweep / "final"), "accepted": bool(results["accepted"]),
                 "reasons": results["reasons"], "exit_code": code, "reused": reused}
    elif best and not args.no_final:
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
           "select": select_record,
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
