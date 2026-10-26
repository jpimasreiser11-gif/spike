"""training/fix_forgetting.py: the checkpoint sweep, then one retrain with self-generated replay, unattended.

Every subprocess is replaced by a recorder that leaves behind what the real script would (a sweep's summary.json, the
replay file, the prepared training set, an adapter and its run.json), and llama-server by a fake that records when it
is started and stopped, so the order of the steps, every command line, the archive and the re-runs after an
interruption at each boundary are checked without a model. The adapter in adapter/ carries a ROUND marker (1: the
rejected run, 2: the retrained one) so a test can tell which run was judged, archived or overwritten.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import fix_forgetting as fix  # noqa: E402

TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ")
SWEEP, REPLAY, PREPARE, TRAIN = "sweep_checkpoints.py", "self_replay.py", "prepare.py", "train_supervised.sh"
FULL = [SWEEP, REPLAY, PREPARE, TRAIN, SWEEP]   # the commands of a run that goes through every step
STEPS = ["sweep1", "archive", "self_replay", "prepare", "train", "sweep2"]
SAVES = 8  # initial input receipt, sweep1, the archive round, archive, self_replay, prepare, train, sweep2


def flag(cmd: list[str], name: str) -> str | None:
    return cmd[cmd.index(name) + 1] if name in cmd else None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class Fake:
    """Replaces fix.run: records every command and leaves what the script would. `verdict`: the sweep's exit code by the
    ROUND of the adapter it judges; `fail`: script -> exit codes to fail with, in order (the run is left half done);
    `kill`: scripts to be killed half way (the orchestrator is interrupted too); `die_after`: the index of the call
    after which the orchestrator is interrupted, the command having finished."""

    def __init__(self, w: SimpleNamespace):
        self.w = w
        self.calls: list[list[str]] = []
        self.events: list[str] = []          # commands and the server's start and stop, in order
        self.verdict = {"1": 2, "2": 0}
        self.fail: dict[str, list[int]] = {}
        self.kill: set[str] = set()
        self.die_after: int | None = None
        self.kept, self.ratio = 1200, 0.3    # self_replay.py's kept answers; the replay share prepare.py reports
        self.sweeps: list[str] = []          # ROUND of the adapter each sweep judged
        self.generated = self.trained = 0    # finished replay files, finished trainings
        self.server_up = False

    def scripts(self) -> list[str]:
        return [Path(c[1]).name for c in self.calls]

    def __call__(self, cmd: list[str]) -> int:
        script = Path(cmd[1]).name
        self.calls.append(cmd)
        self.events.append(script)
        killed = script in self.kill
        self.kill.discard(script)
        code = 137 if killed else self.fail[script].pop(0) if self.fail.get(script) else 0
        done = getattr(self, script.split(".")[0])(cmd, code)
        if killed or self.die_after == len(self.calls) - 1:
            raise KeyboardInterrupt
        return done

    def sweep_checkpoints(self, cmd: list[str], code: int) -> int:
        runs = self.w.runs
        if code or not (runs / "adapter").is_dir():
            return code or 1                 # the real sweep: "no adapter folder"
        rnd = text(runs / "adapter" / "ROUND")
        self.sweeps.append(rnd)
        exit_code = self.verdict[rnd]
        chosen = exit_code == 0 or rnd == "2"
        (runs / "sweep").mkdir(exist_ok=True)
        (runs / "sweep" / "evidence").write_text(rnd, encoding="utf-8")
        (runs / "sweep" / "summary.md").write_text(f"sweep of round {rnd}\n", encoding="utf-8")
        (runs / "sweep" / "summary.json").write_text(json.dumps(
            {"exit_code": exit_code, "chosen": f"spike-medicine-it{rnd}-s0.5" if chosen else None,
             "final": {"accepted": exit_code == 0, "reasons": [f"general: {'-1.00' if exit_code == 0 else '-7.60'} pts "
                                                              "(max drop 1.5)"]} if chosen else None}), encoding="utf-8")
        return exit_code

    def self_replay(self, cmd: list[str], code: int) -> int:
        assert self.server_up, "self_replay.py needs the server"
        out = Path(flag(cmd, "--out"))
        partial = out.with_name(out.name + ".partial")
        assert ("--resume" in cmd) or not partial.exists(), "self_replay.py refuses a .partial without --resume"
        if code:
            partial.write_text("{}\n", encoding="utf-8")
            return code
        out.write_text('{"messages": []}\n' * self.kept, encoding="utf-8")
        out.with_suffix(".summary.json").write_text(json.dumps({"prompts": self.kept + 50, "kept": self.kept}),
                                                    encoding="utf-8")
        partial.unlink(missing_ok=True)
        self.generated += 1
        return 0

    def prepare(self, cmd: list[str], code: int) -> int:
        replay = Path(flag(cmd, "--self-replay"))
        assert replay.is_file()
        data = self.w.data
        (data / "train.jsonl").write_text(f"train from {digest(replay)}\n", encoding="utf-8")
        (data / "valid.jsonl").write_text(f"valid from {digest(replay)}\n", encoding="utf-8")
        (data / "manifest.json").write_text(json.dumps(
            {"files": {f: digest(data / f) for f in ("train.jsonl", "valid.jsonl")},
             "counts": {"domain": 100, "train": 140, "valid": 3, "iters": 140, "replay_ratio_target": 0.3,
                        "replay_ratio_actual": self.ratio},
             "sources": {"oasst2": {"role": "train"}, f"self_replay:{replay.name}": {"role": "train"}}}), encoding="utf-8")
        return code

    def train_supervised(self, cmd: list[str], code: int) -> int:
        runs, data = self.w.runs, self.w.data
        adapter = runs / "adapter"
        adapter.mkdir(exist_ok=True)
        (adapter / "ROUND").write_text("2", encoding="utf-8")
        (adapter / "0000200_adapters.safetensors").write_bytes(b"checkpoint")
        if not code:
            (adapter / "adapters.safetensors").write_bytes(b"round 2")
        (runs / "run.json").write_text(json.dumps(
            {"specialist": "medicine", "started_utc": "2026-10-21T10:00:00Z", "exit_code": code,
             "data_files_sha256": {f: digest(data / f) for f in ("train.jsonl", "valid.jsonl")}}), encoding="utf-8")
        self.trained += not code
        return code


class FakeServer:
    """What fix.py uses of spike.runtime.llamacpp_server.LlamaServer."""

    def __init__(self, config, fake: Fake, fail_start: list):
        self.config, self.fake, self.fail_start = config, fake, fail_start

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    async def start(self, timeout_s: float = 300.0) -> None:
        self.fake.events.append("server start")
        if self.fail_start:
            raise RuntimeError(self.fail_start[0])
        self.fake.server_up = True

    async def stop(self, timeout_s: float = 10.0) -> None:
        self.fake.events.append("server stop")
        self.fake.server_up = False


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A repo root with the real medicine recipe, a finished first run (ROUND 1) with its data, and the fakes."""
    root = tmp_path / "repo"
    (root / "training" / "configs").mkdir(parents=True)
    shutil.copy(ROOT / "training" / "configs" / "medicine.yaml", root / "training" / "configs")
    runs, data = root / "training" / "runs" / "medicine", root / "training" / "data" / "medicine"
    (runs / "adapter").mkdir(parents=True)
    data.mkdir(parents=True)
    (runs / "adapter" / "ROUND").write_text("1", encoding="utf-8")
    (runs / "adapter" / "adapters.safetensors").write_bytes(b"round 1")
    for name in ("train.jsonl", "valid.jsonl"):
        (data / name).write_text(f"round 1 {name}\n", encoding="utf-8")
    (data / "manifest.json").write_text(json.dumps({"sources": {"oasst2": {"role": "train"}}, "counts": {"train": 9}}),
                                        encoding="utf-8")
    (runs / "run.json").write_text(json.dumps(
        {"specialist": "medicine", "started_utc": "2026-10-20T08:40:23Z", "exit_code": 0, "counts": {"iters": 1000},
         "data_files_sha256": {f: digest(data / f) for f in ("train.jsonl", "valid.jsonl")}}), encoding="utf-8")
    (runs / "export.json").write_text('{"gguf": "round 1"}', encoding="utf-8")
    model = tmp_path / "base.gguf"
    model.write_bytes(b"GGUF")
    llama = tmp_path / "llama.cpp"
    llama.mkdir()
    (llama / "convert_lora_to_gguf.py").write_text("", encoding="utf-8")
    w = SimpleNamespace(root=root, runs=runs, data=data, model=model, llama=llama, servers=[], fail_start=[],
                        recipe=root / "training" / "configs" / "medicine.yaml")
    w.fake = fake = Fake(w)

    def make_server(config):
        w.servers.append(FakeServer(config, fake, w.fail_start))
        return w.servers[-1]

    monkeypatch.setattr(fix, "ROOT", root)
    monkeypatch.setattr(fix, "run", fake)
    monkeypatch.setattr(fix, "LlamaServer", make_server)
    monkeypatch.setattr(fix, "find_binary", lambda explicit=None: Path("/fake/llama-server"))
    monkeypatch.setattr(fix, "free_port", lambda: 18091)
    w.args = SimpleNamespace(specialist="medicine", model=str(model), llama_cpp=str(llama), python=None)
    w.go = lambda *extra: fix.main(["medicine", "--llama-cpp", str(llama), "--model", str(model), *extra])
    w.log = lambda: text(runs / "fix_forgetting.log")
    w.state = lambda: json.loads(text(runs / "fix_forgetting.json"))
    w.rounds = lambda: sorted(p.name for p in runs.glob("round*"))
    w.round_of = lambda folder: text(folder / "ROUND")
    return w


def edit_recipe(w, mutate):
    cfg = yaml.safe_load(text(w.recipe))
    mutate(cfg)
    w.recipe.write_text(yaml.safe_dump(cfg), encoding="utf-8")


# ---------------------------------------------------------------------------------------------- the sweep first
def test_an_accepted_sweep_ends_it_and_nothing_else_runs(world, capsys):
    world.fake.verdict["1"] = 0
    assert world.go() == 0
    assert world.fake.scripts() == [SWEEP]
    cmd = world.fake.calls[0]
    assert cmd[0] == sys.executable and cmd[2] == "medicine" and flag(cmd, "--llama-cpp") == str(world.llama)
    assert flag(cmd, "--model") == str(world.model) and "--python" not in cmd
    assert world.servers == [] and world.rounds() == []
    assert world.round_of(world.runs / "adapter") == "1"                   # nothing moved
    assert world.state()["steps"]["sweep1"]["exit_code"] == 0 and "archive_round" not in world.state()
    out = capsys.readouterr().out
    assert "ACCEPTED by the checkpoint sweep on the existing run; nothing was retrained" in out
    assert "training/runs/medicine/sweep/summary.md" in out
    world.fake.calls.clear()
    assert world.go() == 0 and world.fake.calls == []                      # again: the record decides


def test_a_sweep_that_fails_stops_with_an_error_and_moves_nothing(world):
    world.fake.fail[SWEEP] = [1]
    with pytest.raises(SystemExit, match=r"sweep1: sweep_checkpoints.py exited with 1"):
        world.go()
    assert world.fake.scripts() == [SWEEP] and world.rounds() == [] and world.servers == []
    assert world.round_of(world.runs / "adapter") == "1"
    assert world.state()["steps"] == {}                                   # an error is not a finished step
    assert "inputs" in world.state()                                      # input identity survives the failure
    assert "STOPPED: sweep1: sweep_checkpoints.py exited with 1" in world.log()
    assert "run the same command again" in world.log()
    world.fake.verdict["1"] = 0
    assert world.go() == 0 and world.fake.scripts() == [SWEEP, SWEEP]      # fixed: the next run sweeps again


def test_exit_2_without_a_verdict_in_summary_json_is_a_usage_error_not_a_rejection(world):
    world.fake.fail[SWEEP] = [2]                                           # argparse also exits 2
    with pytest.raises(SystemExit, match="does not record that verdict"):
        world.go()
    assert world.rounds() == [] and world.fake.scripts() == [SWEEP]


def test_python_is_passed_to_both_sweeps_and_to_nothing_else(world):
    assert world.go("--python", "/conv/bin/python") == 0
    assert [flag(c, "--python") for c in world.fake.calls] == ["/conv/bin/python", None, None, None, "/conv/bin/python"]


# ----------------------------------------------------------------------------------------------- the whole way
def test_a_rejected_sweep_archives_serves_the_base_alone_generates_prepares_trains_and_sweeps_again(world, capsys):
    recipe_before = text(world.recipe)
    originals = {n: text(world.runs / n) for n in ("run.json", "export.json")}
    manifest = text(world.data / "manifest.json")
    assert world.go() == 0                                                  # sweep2's exit code
    fake = world.fake
    assert fake.scripts() == FULL
    assert fake.events == [SWEEP, "server start", REPLAY, "server stop", PREPARE, TRAIN, SWEEP]

    # the archive: moved, not copied; the records the new round rewrites in place are copies
    assert world.rounds() == ["round1"]
    r1 = world.runs / "round1"
    assert world.round_of(r1 / "adapter") == "1" and text(r1 / "sweep" / "evidence") == "1"
    assert text(r1 / "run.json") == originals["run.json"] and text(r1 / "export.json") == originals["export.json"]
    assert text(r1 / "data-manifest.json") == manifest
    assert world.round_of(world.runs / "adapter") == "2" and text(world.runs / "sweep" / "evidence") == "2"
    assert text(world.runs / "run.json") != originals["run.json"]
    assert fake.sweeps == ["1", "2"]

    # the server: the base GGUF alone, with the chat template, four slots, a context that fits the recipe
    (server,) = world.servers
    command = server.config.command(Path("llama-server"))
    assert server.config.model == world.model and server.config.adapters == []
    assert "--lora" not in command and "--lora-init-without-apply" not in command and "--jinja" in command
    assert flag(command, "--parallel") == "4" and flag(command, "-ngl") == "99"
    assert flag(command, "-c") == str(4 * 2048)                              # max_seq_length 768: 2048 a slot is ample
    assert flag(command, "--cache-type-k") == flag(command, "--cache-type-v") == "q8_0"   # run_eval.py's default
    assert flag(command, "--port") == "18091" and flag(command, "--host") == "127.0.0.1"

    # the other commands
    sweep1, replay, prepare, train, sweep2 = fake.calls
    assert sweep1 == sweep2 == fix.sweep_cmd(fix.load_job(world.args))
    assert replay == [sys.executable, str(world.root / "training" / "self_replay.py"), str(world.recipe),
                      "--base-url", "http://127.0.0.1:18091/v1", "--base-repo", "Qwen/Qwen3.5-4B",
                      "--out", str(world.data / "self_replay.jsonl"), "--concurrency", "4"]
    assert prepare == [sys.executable, str(world.root / "training" / "prepare.py"), str(world.recipe),
                       "--self-replay", str(world.data / "self_replay.jsonl")]
    assert train == ["bash", str(world.root / "training" / "scripts" / "train_supervised.sh"), "medicine"]

    # the recipe is not edited, nothing is installed, committed or pushed
    assert text(world.recipe) == recipe_before
    assert not any(c[0] in ("git", "spike") or "install" in c for c in fake.calls)

    # the record and the log
    state = world.state()
    assert state["archive_round"] == 1 and list(state["steps"]) == STEPS
    assert state["steps"]["sweep1"]["exit_code"] == 2 and state["steps"]["sweep2"]["exit_code"] == 0
    assert state["steps"]["archive"]["dir"] == "training/runs/medicine/round1"
    assert state["steps"]["archive"]["copied"] == ["run.json", "export.json", "data-manifest.json"]
    assert (state["steps"]["self_replay"]["resumed"], state["steps"]["self_replay"]["kept"],
            state["steps"]["self_replay"]["prompts"]) == (False, 1200, 1250)
    assert state["steps"]["prepare"]["replay_ratio_actual"] == 0.3 and state["steps"]["prepare"]["iters"] == 140
    log = world.log()
    assert all(TIME.match(line) for line in log.splitlines())
    out = capsys.readouterr().out
    for part in ("archive: moved", "self_replay: starting llama-server", "llama-server stopped", "prepare: ", "train: ",
                 "sweep2: ", "finished with exit code 0"):
        assert part in log and part in out
    assert "evidence: training/runs/medicine/round1/sweep/summary.md" in log
    assert "evidence: training/runs/medicine/sweep/summary.md" in log
    assert "sweep1, existing run: exit 2, no candidate passed the select rule" in log
    assert "sweep2, new run: exit 0, ACCEPTED spike-medicine-it2-s0.5: general: -1.00 pts (max drop 1.5)" in log
    assert "self-generated replay: prompts 1250, kept 1200" in log
    assert "set replay.self_generated: true" in log and "nothing was committed or pushed" in log


def test_the_second_sweeps_exit_code_is_the_result(world):
    world.fake.verdict["2"] = 2
    assert world.go() == 2
    assert world.fake.scripts() == FULL and world.state()["steps"]["sweep2"]["exit_code"] == 2
    assert "NOT ACCEPTED after round 2" in world.log() and "REJECTED spike-medicine-it2-s0.5" in world.log()
    assert "nothing was installed" not in world.log()
    world.fake.calls.clear()
    assert world.go() == 2 and world.fake.calls == [] and len(world.servers) == 1   # the same answer, no work


def test_the_first_runs_record_looks_finished_on_its_data_until_prepare_rewrites_the_data(world):
    """Why training is only skipped after prepare is done: run.json of round 1 names hashes of the files as they are."""
    assert fix.trained(fix.load_job(world.args)) is True
    assert world.go() == 0
    assert world.fake.scripts().count(TRAIN) == 1 and world.fake.trained == 1


# ---------------------------------------------------------------------------------------------------- archive
def test_the_round_number_is_one_above_the_highest_existing_round(world):
    assert fix.next_round(world.runs) == 1
    for name in ("round1", "round3", "round2x", "rounds", "round", "xround9"):
        (world.runs / name).mkdir()
    (world.runs / "round7.txt").write_text("", encoding="utf-8")
    assert fix.next_round(world.runs) == 4
    assert world.go() == 0
    assert world.round_of(world.runs / "round4" / "adapter") == "1" and world.state()["archive_round"] == 4
    assert (world.runs / "round3").is_dir() and not (world.runs / "round5").exists()


def test_archive_refuses_a_destination_that_exists_and_moves_nothing(world):
    (world.runs / "round1").mkdir()
    (world.runs / "round1" / "keep").write_text("mine", encoding="utf-8")
    state = {"specialist": "medicine", "steps": {}}
    with pytest.raises(SystemExit, match="training/runs/medicine/round1 exists: refusing to archive into it"):
        fix.archive(fix.load_job(world.args), state, 1, False, lambda msg: None)
    assert (world.runs / "adapter" / "ROUND").is_file() and not (world.runs / "round1" / "adapter").exists()
    assert text(world.runs / "round1" / "keep") == "mine"
    assert "archive_round" not in state and not (world.runs / "fix_forgetting.json").exists()   # nothing recorded either


def test_a_folder_present_in_both_places_is_not_moved_over(world):
    (world.runs / "sweep").mkdir()
    (world.runs / "round1" / "sweep").mkdir(parents=True)
    with pytest.raises(SystemExit, match="training/runs/medicine/sweep and training/runs/medicine/round1/sweep both exist"):
        fix.archive(fix.load_job(world.args), {"steps": {}}, 1, True, lambda msg: None)


def test_a_folder_to_archive_that_is_nowhere_is_an_error(world):
    with pytest.raises(SystemExit, match="nothing to archive: training/runs/medicine/sweep does not exist"):
        fix.archive(fix.load_job(world.args), {"steps": {}}, 1, False, lambda msg: None)


def test_an_export_json_or_data_manifest_that_is_not_there_is_not_an_error(world):
    (world.runs / "export.json").unlink()
    (world.data / "manifest.json").unlink()
    (world.runs / "sweep").mkdir()
    record = fix.archive(fix.load_job(world.args), {"steps": {}}, 1, False, lambda msg: None)
    assert record["copied"] == ["run.json"]
    assert sorted(p.name for p in (world.runs / "round1").iterdir()) == ["adapter", "run.json", "sweep"]


def test_a_crash_in_the_middle_of_the_archive_is_finished_not_repeated(world, monkeypatch):
    real_move, moved = shutil.move, []

    def crash_after_first(src, dst):
        real_move(src, dst)
        moved.append(Path(src).name)
        raise KeyboardInterrupt

    monkeypatch.setattr(fix.shutil, "move", crash_after_first)
    with pytest.raises(KeyboardInterrupt):
        world.go()
    assert moved == ["adapter"] and world.state()["archive_round"] == 1 and "archive" not in world.state()["steps"]
    monkeypatch.setattr(fix.shutil, "move", real_move)
    world.fake.calls.clear()
    assert world.go() == 0
    assert world.rounds() == ["round1"]
    assert world.round_of(world.runs / "round1" / "adapter") == "1"
    assert text(world.runs / "round1" / "sweep" / "evidence") == "1"
    assert world.fake.scripts() == [REPLAY, PREPARE, TRAIN, SWEEP]         # sweep1 does not run on a half-moved run
    assert world.state()["steps"]["archive"]["round"] == 1
    assert "continuing an interrupted archive" in world.log()


# ------------------------------------------------------------------------------------------------ the replay
def test_the_server_is_stopped_when_the_replay_fails_and_the_next_run_resumes_it(world):
    world.fake.fail[REPLAY] = [3]
    with pytest.raises(SystemExit, match=r"self_replay.py exited with 3: run the same command again \(--resume"):
        world.go()
    assert world.fake.events == [SWEEP, "server start", REPLAY, "server stop"] and not world.fake.server_up
    assert (world.data / "self_replay.jsonl.partial").is_file() and not (world.data / "self_replay.jsonl").exists()
    assert world.rounds() == ["round1"] and "archive" in world.state()["steps"]
    world.fake.calls.clear()
    assert world.go() == 0
    assert world.fake.scripts() == [REPLAY, PREPARE, TRAIN, SWEEP]         # not archived again, sweep1 not repeated
    assert "--resume" in world.fake.calls[0] and flag(world.fake.calls[0], "--out") == str(world.data / "self_replay.jsonl")
    assert world.rounds() == ["round1"] and len(world.servers) == 2 and not world.fake.server_up
    assert world.state()["steps"]["self_replay"]["resumed"] is True


def test_a_replay_killed_half_way_stops_the_server_and_is_resumed_by_the_next_run(world):
    world.fake.kill.add(REPLAY)
    with pytest.raises(KeyboardInterrupt):
        world.go()
    assert world.fake.events == [SWEEP, "server start", REPLAY, "server stop"] and not world.fake.server_up
    world.fake.calls.clear()
    assert world.go() == 0 and "--resume" in world.fake.calls[0] and world.fake.scripts() == [REPLAY, PREPARE, TRAIN, SWEEP]


def test_a_server_that_does_not_start_is_stopped_too_and_no_replay_runs(world):
    world.fail_start.append("llama-server exited with code 1")
    with pytest.raises(SystemExit, match="llama-server did not start: llama-server exited with code 1"):
        world.go()
    assert world.fake.events == [SWEEP, "server start", "server stop"]
    assert REPLAY not in world.fake.scripts() and "archive" in world.state()["steps"]
    world.fail_start.clear()
    assert world.go() == 0 and world.rounds() == ["round1"]


def test_the_replay_is_skipped_when_it_and_its_summary_exist(world):
    (world.data / "self_replay.jsonl").write_text('{"messages": []}\n', encoding="utf-8")
    (world.data / "self_replay.summary.json").write_text('{"prompts": 5, "kept": 1}', encoding="utf-8")
    assert world.go() == 0
    assert world.fake.scripts() == [SWEEP, PREPARE, TRAIN, SWEEP] and world.servers == []
    assert world.state()["steps"]["self_replay"]["skipped"] is True and "exist, skipped" in world.log()


def test_a_partial_file_adds_resume_and_no_partial_does_not(world):
    assert world.go() == 0
    assert "--resume" not in world.fake.calls[1] and world.fake.scripts()[1] == REPLAY
    (world.runs / "fix_forgetting.json").unlink()
    shutil.rmtree(world.runs / "round1")
    shutil.rmtree(world.runs / "adapter")
    (world.data / "self_replay.jsonl").unlink()
    (world.data / "self_replay.summary.json").unlink()
    (world.data / "self_replay.jsonl.partial").write_text('{"run": {}}\n', encoding="utf-8")
    (world.runs / "adapter").mkdir()
    (world.runs / "adapter" / "ROUND").write_text("1", encoding="utf-8")
    world.fake.calls.clear()
    assert world.go() == 0
    assert "--resume" in world.fake.calls[1] and "continuing self_replay.jsonl.partial" in world.log()


def test_a_replay_file_without_its_summary_is_made_again(world):
    (world.data / "self_replay.jsonl").write_text("stale\n", encoding="utf-8")   # a crash between the two writes
    assert world.go() == 0
    assert world.fake.scripts() == FULL and "--resume" not in world.fake.calls[1]


# ----------------------------------------------------------------------------------- prepare, train, verdict
def test_a_replay_share_below_the_recipes_stops_before_training_and_is_prepared_again_afterwards(world):
    world.fake.ratio = 0.2
    with pytest.raises(SystemExit, match=r"replay is 20.0% of the mix, below the recipe's 30%"):
        world.go()
    assert world.fake.scripts() == [SWEEP, REPLAY, PREPARE] and "prepare" not in world.state()["steps"]
    assert "delete training/data/medicine/self_replay.*" in world.log()
    world.fake.ratio = 0.29                                                 # within prepare.py's own 2-point slack
    world.fake.calls.clear()
    assert world.go() == 0
    assert world.fake.scripts() == [PREPARE, TRAIN, SWEEP]


def test_a_manifest_that_does_not_name_the_replay_file_stops_before_training(world, monkeypatch):
    real = world.fake.prepare

    def ignoring_the_flag(cmd, code):
        real(cmd, code)
        manifest = json.loads(text(world.data / "manifest.json"))
        del manifest["sources"]["self_replay:self_replay.jsonl"]
        (world.data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return 0

    monkeypatch.setattr(world.fake, "prepare", ignoring_the_flag)
    with pytest.raises(SystemExit, match="does not record self_replay.jsonl"):
        world.go()
    assert TRAIN not in world.fake.scripts()


def test_prepare_failing_stops_and_the_next_run_starts_at_prepare(world):
    world.fake.fail[PREPARE] = [1]
    with pytest.raises(SystemExit, match="prepare: prepare.py exited with 1"):
        world.go()
    world.fake.calls.clear()
    assert world.go() == 0 and world.fake.scripts() == [PREPARE, TRAIN, SWEEP]


def test_a_training_that_gives_up_is_continued_by_the_next_run_and_nothing_before_it_repeats(world):
    world.fake.fail[TRAIN] = [75]
    with pytest.raises(SystemExit, match=r"train_supervised.sh exited with 75 \(75: the RAM guard gave up"):
        world.go()
    assert world.fake.scripts() == [SWEEP, REPLAY, PREPARE, TRAIN] and world.fake.trained == 0
    assert "train" not in world.state()["steps"] and not (world.runs / "adapter" / "adapters.safetensors").exists()
    world.fake.calls.clear()
    assert world.go() == 0
    assert world.fake.scripts() == [TRAIN, SWEEP]                           # no archive, replay, prepare or sweep1 again
    assert world.rounds() == ["round1"] and world.fake.trained == 1


def test_a_training_killed_half_way_is_continued_by_the_next_run(world):
    world.fake.kill.add(TRAIN)                                              # checkpoints and a run.json with exit 137
    with pytest.raises(KeyboardInterrupt):
        world.go()
    assert (world.runs / "adapter" / "0000200_adapters.safetensors").is_file()
    assert json.loads(text(world.runs / "run.json"))["exit_code"] == 137
    world.fake.calls.clear()
    assert world.go() == 0 and world.fake.scripts() == [TRAIN, SWEEP] and world.fake.trained == 1


def test_a_training_that_exits_0_without_a_finished_record_is_not_taken_as_finished(world, monkeypatch):
    real = world.fake.train_supervised

    def forgetting_the_record(cmd, code):
        real(cmd, code)
        (world.runs / "run.json").write_text(json.dumps({"exit_code": 0, "data_files_sha256": {}}), encoding="utf-8")
        return 0

    monkeypatch.setattr(world.fake, "train_supervised", forgetting_the_record)
    with pytest.raises(SystemExit, match="exited 0 but training/runs/medicine/run.json does not record a finished run"):
        world.go()
    assert world.fake.scripts() == [SWEEP, REPLAY, PREPARE, TRAIN]


def test_the_second_sweep_failing_is_an_error_and_the_next_run_repeats_only_it(world):
    world.fake.fail[SWEEP] = [0, 1]                                          # sweep1 runs normally, sweep2 fails
    with pytest.raises(SystemExit, match="sweep2: sweep_checkpoints.py exited with 1"):
        world.go()
    world.fake.calls.clear()
    assert world.go() == 0 and world.fake.scripts() == [SWEEP]


# ----------------------------------------------------------------------- interruptions at every boundary
def finish_after_interruption(world):
    """The run again, to the end, and what must hold whatever was interrupted."""
    assert world.go() == 0
    fake = world.fake
    assert world.rounds() == ["round1"]                                     # never archived twice
    assert world.round_of(world.runs / "round1" / "adapter") == "1"         # round 1 never overwritten
    assert text(world.runs / "round1" / "sweep" / "evidence") == "1"
    assert world.round_of(world.runs / "adapter") == "2"
    assert fake.generated == 1 and fake.trained == 1                        # no second replay, no second training
    assert fake.sweeps.count("1") <= 2 and fake.sweeps.count("2") <= 2 and fake.sweeps[-1] == "2"
    assert "1" not in fake.sweeps[fake.sweeps.index("2"):]                  # round 1 is not judged after the archive
    assert list(world.state()["steps"]) == STEPS
    assert not fake.server_up


@pytest.mark.parametrize("k, again", [(0, [SWEEP, REPLAY, PREPARE, TRAIN, SWEEP]), (1, [PREPARE, TRAIN, SWEEP]),
                                      (2, [PREPARE, TRAIN, SWEEP]), (3, [SWEEP]), (4, [SWEEP])],
                         ids=["sweep1", "self_replay", "prepare", "train", "sweep2"])
def test_interrupted_right_after_a_command_finished_it_continues_without_redoing_what_finished(world, k, again):
    world.fake.die_after = k
    with pytest.raises(KeyboardInterrupt):
        world.go()
    assert "STOPPED by an interrupt" in world.log()
    world.fake.die_after = None
    before = len(world.fake.calls)
    finish_after_interruption(world)
    # only the command whose record was lost may run again, where that is harmless: a sweep keeps its work, prepare.py
    # is deterministic and nothing has been trained on its files yet; a finished replay or training is never redone
    assert world.fake.scripts()[before:] == again


@pytest.mark.parametrize("n", range(1, SAVES + 1))
def test_interrupted_just_before_each_record_is_written_it_still_finishes_once(world, monkeypatch, n):
    real, count = fix.save_state, []

    def dying(job, state):
        count.append(1)
        if len(count) == n:
            raise KeyboardInterrupt
        real(job, state)

    monkeypatch.setattr(fix, "save_state", dying)
    with pytest.raises(KeyboardInterrupt):
        world.go()
    monkeypatch.setattr(fix, "save_state", real)
    finish_after_interruption(world)


def test_a_complete_run_writes_the_record_eight_times(world, monkeypatch):
    real, count = fix.save_state, []

    def counting(job, state):
        count.append(1)
        real(job, state)

    monkeypatch.setattr(fix, "save_state", counting)
    assert world.go() == 0 and len(count) == SAVES


# ----------------------------------------------------------------------------------------------------- dry run
def test_dry_run_prints_the_plan_and_runs_and_writes_nothing(world, capsys):
    assert world.go("--dry-run") == 0
    assert world.fake.calls == [] and world.servers == [] and world.fake.events == []
    assert not (world.runs / "fix_forgetting.json").exists() and not (world.runs / "fix_forgetting.log").exists()
    assert not (world.runs / "fix_forgetting.lock").exists() and world.rounds() == []
    out = capsys.readouterr().out
    for part in ("1. sweep1       run:", "2. archive      run: move training/runs/medicine/adapter/ and "
                 "training/runs/medicine/sweep/ to training/runs/medicine/round1/", "data-manifest.json",
                 "3. self_replay  run:", "--jinja", "--port <free port>", "--base-url 'http://127.0.0.1:<port>/v1'",
                 "4. prepare      run:", "--self-replay", "5. train        run:", "train_supervised.sh",
                 "6. sweep2       run:", "0 accepted, 2 rejected"):
        assert part in out
    assert "--lora" not in out and "--resume" not in out


def test_dry_run_after_an_interruption_shows_what_is_done_and_the_resume(world, capsys):
    world.fake.fail[TRAIN] = [75]
    with pytest.raises(SystemExit):
        world.go()
    capsys.readouterr()
    calls = len(world.fake.calls)
    assert world.go("--dry-run") == 0 and len(world.fake.calls) == calls
    out = capsys.readouterr().out
    for part in ("1. sweep1       done (exit 2)", "2. archive      done", "3. self_replay  done",
                 "4. prepare      done", "5. train        run", "6. sweep2       run"):
        assert part in out
    (world.data / "self_replay.jsonl").unlink()
    (world.data / "self_replay.jsonl.partial").write_text("{}\n", encoding="utf-8")
    (world.runs / "fix_forgetting.json").unlink()
    assert world.go("--dry-run") == 0
    assert "--resume" in capsys.readouterr().out


def test_dry_run_with_an_accepted_sweep_says_nothing_else_is_needed(world, capsys):
    world.fake.verdict["1"] = 0
    assert world.go() == 0
    capsys.readouterr()
    assert world.go("--dry-run") == 0
    assert "nothing else: the existing run is accepted" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------- refusals
def refuses(world, match):
    with pytest.raises(SystemExit, match=match):
        world.go()
    assert world.fake.calls == [] and world.servers == []
    assert not (world.runs / "fix_forgetting.json").exists() and not (world.runs / "fix_forgetting.log").exists()


def test_a_recipe_that_already_has_self_generated_replay_is_refused(world):
    edit_recipe(world, lambda cfg: cfg["replay"].update(self_generated=True))
    refuses(world, "already takes its replay from the base model's own answers")


def test_a_recipe_without_replay_sources_is_refused(world):
    edit_recipe(world, lambda cfg: cfg["replay"].update(sources=[]))
    refuses(world, "has no replay.sources")
    edit_recipe(world, lambda cfg: cfg.pop("replay"))
    refuses(world, "has no replay.sources")


def test_a_missing_first_run_record_recipe_or_input_is_refused(world, tmp_path):
    (world.runs / "run.json").unlink()
    refuses(world, "run.json not found: there is no earlier run of medicine to fix")
    (world.runs / "run.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="no recipe at"):
        fix.main(["nothing", "--llama-cpp", str(world.llama), "--model", str(world.model)])
    with pytest.raises(SystemExit, match="base model not found"):
        fix.main(["medicine", "--llama-cpp", str(world.llama), "--model", str(tmp_path / "nope.gguf")])
    with pytest.raises(SystemExit, match="no convert_lora_to_gguf.py"):
        fix.main(["medicine", "--llama-cpp", str(tmp_path), "--model", str(world.model)])
    edit_recipe(world, lambda cfg: cfg["train"].pop("max_seq_length"))
    refuses(world, "no train.max_seq_length")


def test_no_llama_server_is_found_before_anything_runs_unless_it_is_not_needed(world, monkeypatch):
    monkeypatch.setattr(fix, "find_binary", lambda explicit=None: None)
    refuses(world, "llama-server not found")
    (world.data / "self_replay.jsonl").write_text("x\n", encoding="utf-8")
    (world.data / "self_replay.summary.json").write_text("{}", encoding="utf-8")
    assert world.go() == 0                                                  # the replay exists: no server needed


def test_a_damaged_record_is_refused(world):
    (world.runs / "fix_forgetting.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="fix_forgetting.json is not valid JSON"):
        world.go()
    (world.runs / "fix_forgetting.json").write_text('{"steps": []}', encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a fix_forgetting.py record"):
        world.go()
    assert world.fake.calls == []


@pytest.mark.parametrize("changed", ["model", "recipe", "converter", "weights", "run", "summary", "legacy"])
def test_completed_first_sweep_cannot_bypass_input_and_artifact_checks(world, changed):
    world.fake.verdict["1"] = 0
    assert world.go() == 0
    path = {"model": world.model, "recipe": world.recipe,
            "converter": world.llama / "convert_lora_to_gguf.py",
            "weights": world.runs / "adapter/adapters.safetensors", "run": world.runs / "run.json",
            "summary": world.runs / "sweep/summary.json", "legacy": world.runs / "fix_forgetting.json"}[changed]
    if changed == "legacy":
        state = world.state()
        state.pop("inputs", None)
        path.write_text(json.dumps(state))
    else:
        path.write_bytes(path.read_bytes() + b"\n ")
    before = (world.runs / "fix_forgetting.json").read_bytes()
    world.fake.calls.clear()
    with pytest.raises(SystemExit, match="provenance"):
        world.go()
    assert not world.fake.calls
    assert (world.runs / "fix_forgetting.json").read_bytes() == before


@pytest.mark.parametrize("changed", ["round1/adapter/adapters.safetensors", "round1/sweep/summary.json",
                                    "adapter/adapters.safetensors", "sweep/summary.json"])
def test_completed_second_round_checks_both_rounds(world, changed):
    assert world.go() == 0
    path = world.runs / changed
    path.write_bytes(path.read_bytes() + b"\n ")
    world.fake.calls.clear()
    with pytest.raises(SystemExit, match="provenance"):
        world.go()
    assert not world.fake.calls


@pytest.mark.parametrize("changed", ["train.jsonl", "valid.jsonl", "manifest.json", "self_replay.jsonl"])
def test_interrupted_training_refuses_modified_prepared_data(world, changed):
    world.fake.fail[TRAIN] = [75]
    with pytest.raises(SystemExit, match="train_supervised.sh exited"):
        world.go()
    path = world.data / changed
    path.write_bytes(path.read_bytes() + b"\n ")
    world.fake.calls.clear()
    with pytest.raises(SystemExit, match="provenance"):
        world.go()
    assert not world.fake.calls


def test_a_second_instance_is_refused_while_the_first_holds_the_lock(world):
    fcntl = pytest.importorskip("fcntl")
    with (world.runs / "fix_forgetting.lock").open("a", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match="another fix_forgetting.py is running for medicine"):
            world.go()
        assert world.fake.calls == []
    assert world.go() == 0                                                  # released: a stopped run never leaves it stale


# ------------------------------------------------------------------------------------ run(), config, log
class FakeProc:
    def __init__(self, waits):
        self.waits, self.events = list(waits), []

    def wait(self, timeout=None):
        self.events.append(("wait", timeout))
        outcome = self.waits.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def terminate(self):
        self.events.append("terminate")

    def kill(self):
        self.events.append("kill")


def test_run_returns_the_exit_code_of_a_real_command():
    assert fix.run([sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert fix.run([sys.executable, "-c", "pass"]) == 0


def test_run_stops_a_command_with_sigterm_when_interrupted_and_kills_it_after_the_grace_period(monkeypatch):
    proc = FakeProc([KeyboardInterrupt(), 0])
    monkeypatch.setattr(fix.subprocess, "Popen", lambda cmd: proc)
    with pytest.raises(KeyboardInterrupt):
        fix.run(["x"])
    assert proc.events == [("wait", None), "terminate", ("wait", fix.STOP_GRACE_SEC)]
    proc = FakeProc([SystemExit(143), subprocess.TimeoutExpired("x", 60), 0])
    monkeypatch.setattr(fix.subprocess, "Popen", lambda cmd: proc)
    with pytest.raises(SystemExit):
        fix.run(["x"])
    assert proc.events == [("wait", None), "terminate", ("wait", fix.STOP_GRACE_SEC), "kill", ("wait", None)]


def test_the_server_config_gives_each_slot_twice_the_recipes_length_or_2048(world):
    job = fix.load_job(world.args)
    assert fix.server_config(job, 1).context == 4 * 2048
    job.cfg["train"]["max_seq_length"] = 4096
    config = fix.server_config(job, 1)
    assert config.context == 4 * 8192 and config.parallel == 4 and config.adapters == [] and config.kv_cache_type == "q8_0"


def test_the_log_survives_a_console_that_cannot_show_a_character(world, monkeypatch):
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    fix.Log(world.runs / "x.log")("need \u2265 3.0")
    console.flush()
    assert b"need ? 3.0" in console.buffer.getvalue()
    assert "need \u2265 3.0" in text(world.runs / "x.log")


# ----------------------------------------------------------------------- the real llama-server, a tiny model
@pytest.mark.skipif(fix.find_binary() is None, reason="llama-server not installed (set SPIKE_LLAMA_SERVER)")
def test_generate_serves_the_base_model_alone_with_the_real_llama_server_and_stops_it(tmp_path, monkeypatch):
    """The flags of server_config() on the real binary (the tiny model's heads are too small for the q8_0 KV cache, so
    that one is f16 here): it comes up healthy with no adapter applied while the command runs, and is gone once
    generate() returns."""
    import dataclasses

    import httpx

    subprocess.run([sys.executable, str(ROOT / "tests" / "fixtures" / "make_tiny_gguf.py"), str(tmp_path)], check=True,
                   capture_output=True)
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    job = fix.Job("tiny", {"base_model": "x", "train": {"max_seq_length": 768}}, tmp_path / "tiny.yaml", str(tmp_path),
                  tmp_path / "spike-tiny.gguf")
    seen = {}

    def probe(cmd):
        seen["root"] = flag(cmd, "--base-url").removesuffix("/v1")
        seen["health"] = httpx.get(seen["root"] + "/health", timeout=10).status_code
        seen["adapters"] = httpx.get(seen["root"] + "/lora-adapters", timeout=10).json()
        return 0

    real_config = fix.server_config
    monkeypatch.setattr(fix, "run", probe)
    monkeypatch.setattr(fix, "server_config", lambda j, port: dataclasses.replace(real_config(j, port), kv_cache_type="f16"))
    assert fix.generate(job, lambda msg: None, resume=False) == 0
    assert seen["health"] == 200 and seen["adapters"] == []
    with pytest.raises(httpx.HTTPError):
        httpx.get(seen["root"] + "/health", timeout=2)
