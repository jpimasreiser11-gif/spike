"""Fix a rejected-for-forgetting adapter in one detached command, with no hand-off between the steps.

    nohup caffeinate -i python training/fix_forgetting.py medicine --llama-cpp ~/src/llama.cpp --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf > training/runs/medicine/fix_forgetting.out 2>&1 &
    tail -f training/runs/medicine/fix_forgetting.log           # every step with its UTC time; the .out has the tools' output

`caffeinate -i` is macOS (no idle sleep while the command runs); on another OS drop it. Options: [--python CONVERTER_PY]
(passed to both sweeps) and [--dry-run] (print the plan and what is already done; run and write nothing).

One heavy job at a time (the Mac stays usable), stopping at the first accepted result:
1. sweep1: `sweep_checkpoints.py` on the existing run (saved checkpoints, LoRA scale 0.5). Exit 0: accepted, done.
   2: nothing accepted, go on. 1 or anything else: stop with an error, nothing was moved.
2. Round 2 changes ONE thing in the recipe, the replay source: the base model's own answers (training/self_replay.py)
   instead of the human-written ones. Ratio, learning rate, steps formula and acceptance criteria stay; the recipe file
   is not edited (prepare.py --self-replay takes the file in its place). Refused when the recipe already has
   replay.self_generated or no replay.sources, or when training/runs/<id>/run.json is missing.
   a. archive: adapter/ and sweep/ move to training/runs/<id>/round<N>/ (N = 1 + the highest roundK, from 1);
      run.json, export.json and training/data/<id>/manifest.json (as data-manifest.json) are copied there, since the
      new round rewrites them in place. Refused when round<N> exists.
   b. self_replay: llama-server on the base GGUF alone (no adapter; ServerConfig passes --jinja, so thinking is switched
      off per request; 4 slots, a context per slot of at least twice train.max_seq_length, q8_0 KV cache as run_eval.py),
      then self_replay.py (--resume when training/data/<id>/self_replay.jsonl.partial exists). The server is stopped
      however this step ends. Skipped when self_replay.jsonl and self_replay.summary.json exist.
   c. prepare: `prepare.py --self-replay`; stops if the replay share of the mix is below the recipe's ratio (a smoke run's
      few answers would change two things at once) or the manifest does not record the file.
   d. train: `training/scripts/train_supervised.sh` (RAM guard, resumes from its checkpoints).
   e. sweep2: `sweep_checkpoints.py` again, now on the new run. Its exit code is the verdict: 0 accepted, 2 rejected.
Exit code: 0 accepted (by sweep1 or sweep2), 2 nothing accepted, 1 an error (or another instance is running).
Nothing is committed, pushed or installed (~/.spike/adapters is not touched); the end of the log names the sweep
summary.md of each round and the verdicts, and an accepted sweep has printed its `spike adapters install` command.

Run the same command again after any interruption or error: it continues where it stopped. training/runs/<id>/
fix_forgetting.json has the round number and the finished steps: sweep1, archive, prepare and sweep2 are skipped once
recorded (after the archive sweep1's folder has moved, so it must not run again; a half-done archive is finished, never
repeated), while the files decide self_replay (above) and train (run.json: exit 0 on the sha256 of the train/valid files
prepare.py wrote), so training never starts again once finished. Sweeps and self_replay.py resume their own work.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from ramguard import exit_on_signals  # noqa: E402
from spike_train.evaluation import free_port  # noqa: E402

from spike.runtime.llamacpp_server import LlamaServer, ServerConfig, find_binary  # noqa: E402

try:
    import fcntl
except ImportError:  # Windows: no lock, the Mac is the machine this runs on
    fcntl = None

PARALLEL = 4             # llama-server slots and self_replay.py requests in flight
MIN_CTX_PER_SLOT = 2048  # a slot holds a prompt and its answer (train.max_seq_length tokens at most): twice that, or this
NGL = 99                 # GPU layers, run_eval.py's default for Apple silicon
RATIO_SLACK = 0.02       # prepare.py warns when the replay share is further than this below the recipe's ratio
STOP_GRACE_SEC = 60      # a command told to stop (SIGTERM) gets this long before SIGKILL; the RAM guard needs ~30 s
ARCHIVED = ("adapter", "sweep")
ROUND = re.compile(r"^round(\d+)$")


@dataclass
class Job:
    spec: str
    cfg: dict
    recipe: Path
    llama_cpp: str
    model: Path
    python: str | None = None

    @property
    def runs(self) -> Path:
        return ROOT / "training" / "runs" / self.spec

    @property
    def data(self) -> Path:
        return ROOT / "training" / "data" / self.spec

    @property
    def replay(self) -> Path:
        return self.data / "self_replay.jsonl"

    @property
    def partial(self) -> Path:
        return self.replay.with_name(self.replay.name + ".partial")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def shown(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()  # the same record on every OS
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Log:
    """Every line to stdout and to training/runs/<id>/fix_forgetting.log, behind its UTC time."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            for part in msg.splitlines() or [""]:
                line = f"{now()} {part}"
                f.write(line + "\n")
                try:
                    print(line, flush=True)
                except UnicodeEncodeError:  # a console that cannot show every sign of a sweep's reasons: the file can
                    print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def run(cmd: list[str]) -> int:
    """The command's exit code. When this process is stopped meanwhile (Ctrl-C, SIGTERM) the command gets SIGTERM, so the
    RAM guard stops its training in order, and SIGKILL after STOP_GRACE_SEC."""
    proc = subprocess.Popen(cmd)
    try:
        return proc.wait()
    except BaseException:
        proc.terminate()
        try:
            proc.wait(STOP_GRACE_SEC)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise


@contextlib.contextmanager
def exclusive(job: Job):
    """One fix_forgetting.py per specialist at a time: two would train into one adapter folder. An OS lock on a file,
    released when this process ends however it ends, so a killed run never leaves it stale."""
    if fcntl is None:
        yield
        return
    with (job.runs / "fix_forgetting.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(f"another fix_forgetting.py is running for {job.spec} (it holds "
                             f"{shown(job.runs / 'fix_forgetting.lock')}): wait for it, or stop it first") from None
        yield


# --------------------------------------------------------------------------------------------------- the inputs
def load_job(args: argparse.Namespace) -> Job:
    spec = args.specialist
    recipe = ROOT / "training" / "configs" / f"{spec}.yaml"
    if not recipe.is_file():
        raise SystemExit(f"no recipe at {recipe}")
    cfg = yaml.safe_load(recipe.read_text(encoding="utf-8"))
    replay = cfg.get("replay") or {}
    if not replay.get("sources"):
        raise SystemExit(f"{shown(recipe)} has no replay.sources: self_replay.py takes its prompts from them, and there "
                         "is no replay to take from the base model's own answers (nothing to change)")
    if replay.get("self_generated"):
        raise SystemExit(f"{shown(recipe)} already takes its replay from the base model's own answers "
                         "(replay.self_generated): the one change this command makes is already in the recipe")
    if not (cfg.get("train") or {}).get("max_seq_length"):
        raise SystemExit(f"{shown(recipe)} has no train.max_seq_length: self_replay.py needs it to bound the answers")
    runs = ROOT / "training" / "runs" / spec
    if not (runs / "run.json").is_file():
        raise SystemExit(f"{runs / 'run.json'} not found: there is no earlier run of {spec} to fix (train first)")
    model = Path(args.model).expanduser()
    if not model.is_file():
        raise SystemExit(f"base model not found: {model}")
    llama_cpp = Path(args.llama_cpp).expanduser()
    if not (llama_cpp / "convert_lora_to_gguf.py").is_file():
        raise SystemExit(f"{args.llama_cpp} has no convert_lora_to_gguf.py: pass the llama.cpp checkout")
    return Job(spec, cfg, recipe, str(llama_cpp), model, args.python)


def state_path(job: Job) -> Path:
    return job.runs / "fix_forgetting.json"


def read_state(job: Job) -> dict:
    path = state_path(job)
    if not path.is_file():
        return {"specialist": job.spec, "steps": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise SystemExit(f"{shown(path)} is not valid JSON: repair it, or delete it to start from the sweep again") from None
    if not isinstance(state, dict) or not isinstance(state.get("steps"), dict):
        raise SystemExit(f"{shown(path)} is not a fix_forgetting.py record: repair it, or delete it")
    return state


def save_state(job: Job, state: dict) -> None:
    path = state_path(job)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # a reader (or a kill) never sees half a record


def mark(job: Job, state: dict, step: str, **info) -> dict:
    state["steps"][step] = {"utc": now(), **info}
    save_state(job, state)
    return state["steps"][step]


def read_json(path: Path) -> dict:
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


# ------------------------------------------------------------------------------------------------- the commands
def sweep_cmd(job: Job) -> list[str]:
    cmd = [sys.executable, str(ROOT / "training" / "sweep_checkpoints.py"), job.spec, "--llama-cpp", job.llama_cpp,
           "--model", str(job.model)]
    return cmd + ["--python", job.python] if job.python else cmd


def self_replay_cmd(job: Job, base_url: str, resume: bool) -> list[str]:
    cmd = [sys.executable, str(ROOT / "training" / "self_replay.py"), str(job.recipe), "--base-url", base_url,
           "--base-repo", job.cfg["base_model"], "--out", str(job.replay), "--concurrency", str(PARALLEL)]
    return cmd + ["--resume"] if resume else cmd


def prepare_cmd(job: Job) -> list[str]:
    return [sys.executable, str(ROOT / "training" / "prepare.py"), str(job.recipe), "--self-replay", str(job.replay)]


def train_cmd(job: Job) -> list[str]:
    return ["bash", str(ROOT / "training" / "scripts" / "train_supervised.sh"), job.spec]


def server_config(job: Job, port: int) -> ServerConfig:
    """The base model alone: no adapters, so no --lora (self_replay.py checks that too). command() always passes --jinja
    (the chat template, so each request can switch thinking off) and q8_0 KV, the runtime's and run_eval.py's default."""
    per_slot = max(MIN_CTX_PER_SLOT, 2 * job.cfg["train"]["max_seq_length"])
    return ServerConfig(model=job.model, port=port, context=per_slot * PARALLEL, parallel=PARALLEL, gpu_layers=NGL)


# ----------------------------------------------------------------------------------------------------- the steps
def sweep_step(job: Job, state: dict, log: Log, step: str) -> dict:
    """sweep_checkpoints.py on the run in adapter/ (it keeps its own finished work, so a repeat is cheap). Exit 0 and 2
    are verdicts, and only when its summary.json says the same: argparse also exits 2, on a bad command line."""
    cmd = sweep_cmd(job)
    log(f"{step}: {shlex.join(cmd)}")
    code = run(cmd)
    log(f"{step}: sweep_checkpoints.py exited with {code}")
    if code not in (0, 2):
        raise SystemExit(f"{step}: sweep_checkpoints.py exited with {code}: fix the cause and run the same command again "
                         "(the finished exports and answers are kept)")
    if read_json(job.runs / "sweep" / "summary.json").get("exit_code") != code:
        raise SystemExit(f"{step}: sweep_checkpoints.py exited with {code} but {shown(job.runs / 'sweep' / 'summary.json')} "
                         "does not record that verdict")
    return mark(job, state, step, exit_code=code)


def next_round(runs: Path) -> int:
    return max((int(m.group(1)) for p in runs.iterdir() if (m := ROUND.match(p.name))), default=0) + 1


def archive(job: Job, state: dict, n: int, resuming: bool, log: Log) -> dict:
    """Move adapter/ and sweep/ into round<N>/ and copy run.json, export.json and the data manifest there (the next round
    rewrites those in place). N is recorded in the state before anything moves, so a re-run finishes this archive. What
    an interrupted attempt already did is skipped, never repeated; round<N> existing without such an attempt, or a
    folder present both here and there, is refused."""
    dest = job.runs / f"round{n}"
    if dest.exists() and not resuming:
        raise SystemExit(f"{shown(dest)} exists: refusing to archive into it, nothing was moved")
    if not resuming:
        state["archive_round"] = n
        save_state(job, state)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVED:
        src, to = job.runs / name, dest / name
        if to.exists():
            if src.exists():
                raise SystemExit(f"{shown(src)} and {shown(to)} both exist: not moving one over the other")
            continue  # an interrupted attempt moved it
        if not src.exists():
            raise SystemExit(f"nothing to archive: {shown(src)} does not exist")
        shutil.move(str(src), str(to))
        log(f"archive: moved {shown(src)} -> {shown(to)}")
    copied = []
    for src, to in ((job.runs / "run.json", dest / "run.json"), (job.runs / "export.json", dest / "export.json"),
                    (job.data / "manifest.json", dest / "data-manifest.json")):
        if to.exists():
            continue
        if not src.is_file():
            log(f"archive: {shown(src)} does not exist, nothing to copy")
            continue
        tmp = to.with_name(to.name + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, to)
        copied.append(to.name)
        log(f"archive: copied {shown(src)} -> {shown(to)}")
    return {"round": n, "dir": shown(dest), "moved": list(ARCHIVED), "copied": copied}


def archive_step(job: Job, state: dict, log: Log) -> None:
    if "archive" in state["steps"]:
        log(f"archive: already done ({state['steps']['archive']['dir']}), skipped")
        return
    resuming = "archive_round" in state
    n = state["archive_round"] if resuming else next_round(job.runs)
    log(f"archive: round {n}" + (" (continuing an interrupted archive)" if resuming else ""))
    mark(job, state, "archive", **archive(job, state, n, resuming, log))


def replay_done(job: Job) -> bool:
    return job.replay.is_file() and job.replay.with_suffix(".summary.json").is_file()


def generate(job: Job, log: Log, resume: bool) -> int:
    """self_replay.py against a llama-server on the base model alone, which is stopped however this ends."""
    server = LlamaServer(server_config(job, free_port()))
    log(f"self_replay: starting llama-server on {job.model.name} alone: "
        f"{shlex.join(server.config.command(find_binary(server.config.binary) or Path('llama-server')))}")
    try:
        try:
            asyncio.run(server.start())
        except Exception as exc:
            raise SystemExit(f"self_replay: llama-server did not start: {exc}") from exc
        log(f"self_replay: llama-server ready at {server.base_url}")
        cmd = self_replay_cmd(job, f"{server.base_url}/v1", resume)
        log(f"self_replay: {shlex.join(cmd)}")
        return run(cmd)
    finally:
        try:
            asyncio.run(server.stop())
            log("self_replay: llama-server stopped")
        except Exception as exc:  # the step's own outcome matters more than a failed stop
            log(f"self_replay: stopping llama-server failed: {exc}")


def replay_counts(job: Job) -> dict:
    summary = read_json(job.replay.with_suffix(".summary.json"))
    return {key: summary[key] for key in ("prompts", "kept") if key in summary}


def self_replay_step(job: Job, state: dict, log: Log) -> None:
    if replay_done(job):
        log(f"self_replay: {shown(job.replay)} and {job.replay.with_suffix('.summary.json').name} exist, skipped")
        if "self_replay" not in state["steps"]:
            mark(job, state, "self_replay", skipped=True, **replay_counts(job))
        return
    resume = job.partial.exists()
    log("self_replay: " + (f"continuing {job.partial.name}" if resume else "from the start"))
    if code := generate(job, log, resume):
        raise SystemExit(f"self_replay: self_replay.py exited with {code}: run the same command again (--resume "
                         f"continues {job.partial.name}; if its message says the partial was made with other settings, "
                         "delete it)")
    if not replay_done(job):
        raise SystemExit(f"self_replay: self_replay.py exited 0 but {shown(job.replay)} or its summary is missing")
    mark(job, state, "self_replay", resumed=resume, **replay_counts(job))


def check_mix(job: Job) -> dict:
    """What prepare.py wrote, against what this round promises: the file was used and the replay share is the recipe's."""
    manifest = read_json(job.data / "manifest.json")
    key = f"self_replay:{job.replay.name}"
    if key not in (manifest.get("sources") or {}):
        raise SystemExit(f"prepare: {shown(job.data / 'manifest.json')} does not record {job.replay.name}: the training set "
                         "was not built from the base model's own answers")
    counts = manifest.get("counts") or {}
    target, actual = counts.get("replay_ratio_target"), counts.get("replay_ratio_actual")
    if not isinstance(target, int | float) or not isinstance(actual, int | float):
        raise SystemExit(f"prepare: {shown(job.data / 'manifest.json')} has no replay ratio in counts")
    if target - actual > RATIO_SLACK:
        raise SystemExit(f"prepare: replay is {actual:.1%} of the mix, below the recipe's {target:.0%}: {job.replay.name} has "
                         f"too few answers (a --limit smoke run, or many were dropped: see "
                         f"{shown(job.replay.with_suffix('.summary.json'))}). Training was not started, so the replay source "
                         f"stays the only change; delete training/data/{job.spec}/self_replay.* and run the same command again")
    return {key: counts[key] for key in ("domain", "replay_available", "train", "valid", "iters") if key in counts} | {
        "replay_ratio_actual": actual}


def prepare_step(job: Job, state: dict, log: Log) -> None:
    if "prepare" in state["steps"]:
        log("prepare: already done, skipped")
        return
    cmd = prepare_cmd(job)
    log(f"prepare: {shlex.join(cmd)}")
    if code := run(cmd):
        raise SystemExit(f"prepare: prepare.py exited with {code}: fix the cause and run the same command again")
    mark(job, state, "prepare", **check_mix(job))


def trained(job: Job) -> bool:
    """Training finished on the data prepare.py wrote last: run.json records exit 0 and the sha256 of both files as they
    are now, and the final adapter exists. Only meaningful once prepare is done: before that, run.json is the old run's."""
    record = read_json(job.runs / "run.json")
    hashes = record.get("data_files_sha256") or {}
    files = [job.data / "train.jsonl", job.data / "valid.jsonl"]
    return (record.get("exit_code") == 0 and all(f.is_file() and hashes.get(f.name) == sha256(f) for f in files)
            and (job.runs / "adapter" / "adapters.safetensors").is_file())


def train_step(job: Job, state: dict, log: Log) -> None:
    if trained(job):
        log("train: run.json records a finished run on this training set, skipped")
        if "train" not in state["steps"]:
            mark(job, state, "train", skipped=True)
        return
    cmd = train_cmd(job)
    log(f"train: {shlex.join(cmd)}")
    if code := run(cmd):
        raise SystemExit(f"train: train_supervised.sh exited with {code} (75: the RAM guard gave up after MAX_RESTARTS): "
                         "run the same command again, training continues from its last checkpoint")
    if not trained(job):
        raise SystemExit(f"train: train_supervised.sh exited 0 but {shown(job.runs / 'run.json')} does not record a finished "
                         f"run on training/data/{job.spec}/train.jsonl and valid.jsonl")
    mark(job, state, "train")


# ------------------------------------------------------------------------------------------------ the end report
def verdict(path: Path) -> str:
    out = read_json(path)
    if not out:
        return f"no {path.name} to read"
    if not out.get("chosen"):
        return "no candidate passed the select rule"
    final = out.get("final") or {}
    return f"{'ACCEPTED' if final.get('accepted') else 'REJECTED'} {out['chosen']}: " + "; ".join(final.get("reasons") or [])


def report(job: Job, state: dict, code: int, log: Log) -> None:
    steps = state["steps"]
    first = (job.runs / f"round{steps['archive']['round']}" if "archive" in steps else job.runs) / "sweep"
    second = job.runs / "sweep"
    log("summary:")
    if steps["sweep1"]["exit_code"] == 0:
        log(f"fix_forgetting {job.spec}: ACCEPTED by the checkpoint sweep on the existing run; nothing was retrained")
    else:
        log(f"fix_forgetting {job.spec}: " + ("ACCEPTED" if code == 0 else "NOT ACCEPTED") + " after round 2 "
            "(replay from the base model's own answers)")
    log(f"  sweep1, existing run: exit {steps['sweep1']['exit_code']}, {verdict(first / 'summary.json')}")
    log(f"    evidence: {shown(first / 'summary.md')}")
    if "archive" in steps:
        log(f"  archived the first run as {steps['archive']['dir']}/ (adapter, sweep; run.json, export.json, data-manifest.json)")
        counts = ", ".join(f"{k} {v}" for k, v in steps.get("self_replay", {}).items() if k in ("kept", "prompts"))
        log(f"  self-generated replay: {counts or 'done'} ({shown(job.replay)}); trained on it, run record "
            f"{shown(job.runs / 'run.json')}")
    if "sweep2" in steps:
        log(f"  sweep2, new run: exit {steps['sweep2']['exit_code']}, {verdict(second / 'summary.json')}")
        log(f"    evidence: {shown(second / 'summary.md')}")
    if code == 0:
        log("  nothing was installed: the sweep printed the `spike adapters install` command (in the .out); "
            f"{shlex.join(sweep_cmd(job))} prints it again from the saved results")
    if "sweep2" in steps:
        log(f"  {shown(job.recipe)} was not edited and still lists the human-written replay sources; the new run used "
            f"--self-replay (training/data/{job.spec}/manifest.json): set replay.self_generated: true in the recipe "
            "when you commit it")
    log("  nothing was committed or pushed")


def execute(job: Job, state: dict, log: Log) -> int:
    steps = state["steps"]
    first = steps.get("sweep1") or sweep_step(job, state, log, "sweep1")
    if first["exit_code"] == 0:
        report(job, state, 0, log)
        return 0
    log("sweep1: nothing accepted on the existing run; round 2 changes the replay source and nothing else")
    archive_step(job, state, log)
    self_replay_step(job, state, log)
    prepare_step(job, state, log)
    train_step(job, state, log)
    last = steps.get("sweep2") or sweep_step(job, state, log, "sweep2")
    report(job, state, last["exit_code"], log)
    return last["exit_code"]


def plan_lines(job: Job, state: dict) -> list[str]:
    """What a run would do now, step by step, from the record and the files; nothing is run or written."""
    steps = state["steps"]

    def status(step: str, done: bool, todo: str = "run") -> str:
        return f"done (exit {steps[step]['exit_code']})" if done and "exit_code" in steps.get(step, {}) else (
            "done" if done else todo)

    dest = shown(job.runs / f"round{state.get('archive_round') or next_round(job.runs)}")
    config = server_config(job, 0)
    binary = find_binary(config.binary) or Path("llama-server")
    server = shlex.join(config.command(binary)).replace("--port 0", "--port <free port>")
    lines = [f"fix_forgetting {job.spec}: plan from {shown(state_path(job))} and the files (--dry-run: nothing is run)",
             f"  1. sweep1       {status('sweep1', 'sweep1' in steps)}: {shlex.join(sweep_cmd(job))}",
             "                  exit 0: accepted, stop; 2: go on; anything else: stop with an error"]
    if steps.get("sweep1", {}).get("exit_code") == 0:
        return [*lines, "  nothing else: the existing run is accepted"]
    resume = job.partial.exists()
    return [*lines,
            f"  2. archive      {status('archive', 'archive' in steps, 'continue' if 'archive_round' in state else 'run')}: "
            f"move {' and '.join(f'training/runs/{job.spec}/{a}/' for a in ARCHIVED)} to {dest}/, copy run.json, export.json "
            f"and training/data/{job.spec}/manifest.json (as data-manifest.json) there",
            f"  3. self_replay  {status('self_replay', replay_done(job), 'resume' if resume else 'run')}: {server}",
            f"                  {shlex.join(self_replay_cmd(job, 'http://127.0.0.1:<port>/v1', resume))}",
            f"  4. prepare      {status('prepare', 'prepare' in steps)}: {shlex.join(prepare_cmd(job))}",
            f"  5. train        {status('train', 'prepare' in steps and trained(job))}: {shlex.join(train_cmd(job))}",
            f"  6. sweep2       {status('sweep2', 'sweep2' in steps)}: {shlex.join(sweep_cmd(job))}",
            "                  its exit code is the result: 0 accepted, 2 rejected"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Checkpoint sweep, then one retrain with self-generated replay, unattended.")
    ap.add_argument("specialist")
    ap.add_argument("--llama-cpp", required=True, help="llama.cpp checkout containing convert_lora_to_gguf.py")
    ap.add_argument("--model", required=True, help="base GGUF: served alone for the replay, and what the sweeps evaluate on")
    ap.add_argument("--python", help="interpreter with the converter's requirements (passed to both sweeps)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and what is already done; run and write nothing")
    args = ap.parse_args(argv)

    job = load_job(args)
    state = read_state(job)
    if state["steps"].get("sweep1", {}).get("exit_code") != 0 and not replay_done(job) and find_binary() is None:
        raise SystemExit("llama-server not found: install llama.cpp (e.g. `brew install llama.cpp`) or set SPIKE_LLAMA_SERVER; "
                         "the replay is generated with it")
    if args.dry_run:
        print("\n".join(plan_lines(job, state)))
        return 0
    with exclusive(job):
        log = Log(job.runs / "fix_forgetting.log")
        state = read_state(job)  # again, now that no other instance can change it
        log(f"fix_forgetting {job.spec}: started; finished before: {', '.join(state['steps']) or 'nothing'}")
        try:
            code = execute(job, state, log)
        except SystemExit as exc:
            log(f"STOPPED: {exc.code}" if isinstance(exc.code, str) else f"STOPPED by a signal (exit {exc.code})")
            log("run the same command again to continue where it stopped")
            raise
        except KeyboardInterrupt:
            log("STOPPED by an interrupt: run the same command again to continue where it stopped")
            raise
        log(f"fix_forgetting {job.spec}: finished with exit code {code}")
        return code


if __name__ == "__main__":
    exit_on_signals()
    raise SystemExit(main())
