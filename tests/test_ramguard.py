"""RAM guard: the stop/wait/resume decisions as pure functions, and the supervisor loop with a fake trainer process
(a short Python script) and fake memory readings on a virtual clock. No mlx, no model."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

import ramguard  # noqa: E402
from ramguard import Config, Mem, may_resume, stable_since, stop_reason  # noqa: E402

posix = pytest.mark.skipif(sys.platform == "win32", reason="process groups and signals are POSIX")

CFG = Config()   # SWAP_GROWTH_GB 2, MIN_FREE_GB 2.5, RESUME_FREE_GB 22, RESUME_STABLE_MIN 10, MAX_RESTARTS 20


# ---- decisions, as pure functions -------------------------------------------------------------------------------

def test_defaults_and_env_overrides():
    assert (CFG.swap_growth_gb, CFG.min_free_gb, CFG.resume_free_gb, CFG.resume_stable_min, CFG.max_restarts) == (2, 2.5, 22, 10, 20)
    cfg = Config.from_env({"SWAP_GROWTH_GB": "1.5", "MIN_FREE_GB": "4", "RESUME_FREE_GB": "30", "RESUME_STABLE_MIN": "3",
                           "MAX_RESTARTS": "2", "SAMPLE_SEC": "", "UNRELATED": "x"})
    assert (cfg.swap_growth_gb, cfg.min_free_gb, cfg.resume_free_gb, cfg.resume_stable_min, cfg.max_restarts) == (1.5, 4, 30, 3, 2)
    assert cfg.sample_sec == 5   # empty means default
    with pytest.raises(SystemExit, match="MAX_RESTARTS='lots'"):
        Config.from_env({"MAX_RESTARTS": "lots"})


def test_stop_on_swap_growth_over_the_baseline_not_on_swap_in_use():
    assert stop_reason(Mem(20, 11.0), swap_base_gb=11.0, cfg=CFG) is None   # lots of swap, none new
    assert stop_reason(Mem(20, 9.0), swap_base_gb=7.1, cfg=CFG) is None   # +1.9 GB
    assert stop_reason(Mem(20, 9.1), swap_base_gb=7.1, cfg=CFG) is None   # exactly 2.0 GB is not more than 2
    why = stop_reason(Mem(20, 11.3), swap_base_gb=7.1, cfg=CFG)   # the evening's numbers
    assert why and "swap grew 4.20 GB" in why and "7.10 -> 11.30" in why
    assert stop_reason(Mem(20, 5.0), swap_base_gb=7.1, cfg=CFG) is None   # swap shrank


def test_stop_on_low_available_memory():
    assert stop_reason(Mem(2.5, 0), 0, CFG) is None
    why = stop_reason(Mem(2.49, 0), 0, CFG)
    assert why and "2.49 GB" in why and "below 2.5" in why
    assert "3.70" in stop_reason(Mem(3.7, 4.0), 0, Config(swap_growth_gb=100, min_free_gb=5))   # the reason carries the reading


def test_resume_only_after_enough_free_memory_held_for_long_enough():
    cfg = Config(resume_free_gb=22, resume_stable_min=10)
    since = stable_since(None, 100.0, Mem(21.9, 0), cfg)
    assert since is None   # not enough
    since = stable_since(since, 200.0, Mem(22.0, 0), cfg)
    assert since == 200.0   # timer starts
    assert stable_since(since, 500.0, Mem(40, 0), cfg) == 200.0   # keeps its start while it stays high
    assert not may_resume(since, 799.9, cfg) and may_resume(since, 800.0, cfg)
    assert stable_since(since, 600.0, Mem(5, 0), cfg) is None   # one dip resets it
    assert not may_resume(None, 10**9, cfg)


# ---- the supervisor, with a fake trainer ------------------------------------------------------------------------

TRAINER = textwrap.dedent('''
    import json, os, signal, subprocess, sys, time
    from pathlib import Path
    d, modes = Path(sys.argv[1]), sys.argv[2].split(",")
    n = len(list(d.glob("attempt-*.json"))) + 1
    mode = modes[min(n, len(modes)) - 1]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])   # a grandchild, like python | tee
    if mode == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (d / f"attempt-{n}.json").write_text(json.dumps(   # the test waits for this file: the trainer is up
        {"pid": os.getpid(), "child": child.pid, "resume": os.environ.get("SPIKE_RESUME"), "mode": mode}))
    if mode.startswith("run:"):   # run:<seconds>:<exit code>
        time.sleep(float(mode.split(":")[1]))
        child.kill()
        sys.exit(int(mode.split(":")[2]))
    time.sleep(600)
''')


class Sim:
    """Fake memory readings on a virtual clock: `sleep` advances the clock (and really waits a few ms so that the
    trainer process can die). `schedule` is [(from virtual second, Mem)]; the last entry at or before now holds."""

    def __init__(self, tmp_path, modes, schedule, **cfg):
        self.dir = tmp_path
        self.modes, self.schedule, self.now, self.launched, self.reads = modes, schedule, 0.0, [], []
        self.cfg = Config(sample_sec=10, grace_sec=10, resume_stable_min=10, log_every_sec=300, **cfg)
        (tmp_path / "trainer.py").write_text(TRAINER)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        time.sleep(0.005)
        self.now += seconds

    def read(self):
        mem = [m for t, m in self.schedule if t <= self.now][-1]
        self.reads.append((self.now, mem))
        return mem

    def attempts(self):
        return [json.loads(p.read_text()) for p in sorted(self.dir.glob("attempt-*.json"))]

    def log(self):
        return (self.dir / "ramguard.log").read_text()

    def run(self, monkeypatch):
        real = subprocess.Popen

        def launch(*args, **kw):
            self.launched.append(self.now)
            proc = real(*args, **kw)
            started = self.dir / f"attempt-{len(self.launched)}.json"
            for _ in range(500):   # up to 10 s for the trainer to start, so that a stop never beats its first line
                if started.exists() or proc.poll() is not None:
                    break
                time.sleep(0.02)
            return proc

        monkeypatch.setattr(ramguard.subprocess, "Popen", launch)
        cmd = [sys.executable, str(self.dir / "trainer.py"), str(self.dir), self.modes]
        return ramguard.supervise(cmd, self.dir, self.cfg, read=self.read, clock=self.clock, sleep=self.sleep)


def gone(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE   # a zombie only waits to be reaped
    except psutil.NoSuchProcess:
        return True


def all_gone(attempts):
    return all(gone(a[k]) for a in attempts for k in ("pid", "child"))


@posix
def test_normal_exit_is_passed_through_and_not_restarted(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "run:0.3:0", [(0, Mem(30, 5))])
    assert sim.run(monkeypatch) == 0
    assert len(sim.attempts()) == 1 and "exited on its own with code 0; not restarting" in sim.log()


@posix
def test_a_crash_exit_code_is_passed_through_too(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "run:0.3:7", [(0, Mem(30, 5))])
    assert sim.run(monkeypatch) == 7
    assert len(sim.attempts()) == 1 and "code 7" in sim.log()


@posix
def test_stops_on_swap_growth_waits_then_relaunches_with_resume_and_a_new_swap_baseline(tmp_path, monkeypatch):
    # attempt 1 starts with 5.0 GB of swap in use; at t=20 s it is 7.5 (+2.5 > 2): stop. Memory is 10 GB free until
    # t=120, so the supervisor waits; attempt 2 then starts with 7.5 GB swap in use, which is its baseline: no stop.
    sim = Sim(tmp_path, "hang,run:1:0", [(0, Mem(30, 5.0)), (20, Mem(10, 7.5)), (120, Mem(30, 7.5))])
    assert sim.run(monkeypatch) == 0
    first, second = sim.attempts()
    assert first["resume"] == second["resume"] == "1"
    log = sim.log()
    assert "attempt 1: STOP, swap grew 2.50 GB" in log and "7.50" in log
    assert "still running after" not in log   # SIGTERM was enough
    assert "waiting for 22 GB available for 10 min" in log and "restart 1 of at most 20: relaunching with SPIKE_RESUME=1" in log
    assert sim.launched[1] >= 120 + 600   # not before 10 minutes of >= 22 GB
    assert all_gone(sim.attempts())   # the trainer and its grandchild


@posix
def test_the_first_attempt_waits_too_when_the_machine_is_busy_at_launch(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "run:0.2:0", [(0, Mem(8, 11.3)), (100, Mem(30, 11.3))])
    assert sim.run(monkeypatch) == 0
    assert sim.launched[0] >= 100 + 600 and len(sim.attempts()) == 1
    assert sim.log().index("waiting for 22 GB") < sim.log().index("attempt 1: started")


@posix
def test_stops_on_low_available_memory(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "hang,run:0.2:0", [(0, Mem(30, 5.0)), (15, Mem(2.0, 5.0)), (50, Mem(30, 5.0))])
    assert sim.run(monkeypatch) == 0
    assert "attempt 1: STOP, available memory 2.00 GB is below 2.5 GB" in sim.log()
    assert len(sim.attempts()) == 2 and all_gone(sim.attempts())


@posix
def test_waits_until_memory_has_been_free_for_the_whole_stable_time(tmp_path, monkeypatch):
    # stop at t=20; free from t=120 to 420 (5 min: not enough), a dip, free again from t=470: ready at 470 + 600
    sim = Sim(tmp_path, "hang,run:0.2:0",
              [(0, Mem(30, 5.0)), (20, Mem(10, 8.0)), (120, Mem(30, 8.0)), (420, Mem(5, 8.0)), (470, Mem(30, 8.0))])
    assert sim.run(monkeypatch) == 0
    log = sim.log()
    assert log.count("timer started") == 2 and log.count("timer reset") == 1
    assert 470 + 600 <= sim.launched[1] < 470 + 600 + 30
    assert "still waiting" in log   # status lines while idle (every LOG_EVERY_SEC)


@posix
def test_gives_up_after_max_restarts(tmp_path, monkeypatch):
    class Growing(Sim):   # every attempt's swap grows 3 GB, 20 s after it was launched
        def read(self):
            return Mem(30, 5.0 + 3.0 * sum(self.now >= t + 20 for t in self.launched))

    sim = Growing(tmp_path, "hang", [(0, Mem(30, 5.0))], max_restarts=2)
    assert sim.run(monkeypatch) == ramguard.GAVE_UP == 75
    assert len(sim.attempts()) == 3   # the first run and two restarts
    assert "giving up: stopped 3 times, MAX_RESTARTS=2" in sim.log() and sim.log().count("STOP") == 3
    assert all_gone(sim.attempts())


@posix
def test_sigkill_after_the_grace_period_when_the_trainer_ignores_sigterm(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "stubborn,run:0.2:0", [(0, Mem(30, 5.0)), (10, Mem(1.0, 5.0)), (30, Mem(30, 5.0))])
    assert sim.run(monkeypatch) == 0
    assert "still running after 10 s: SIGKILL" in sim.log()
    assert all_gone(sim.attempts())


@posix
def test_stopping_the_supervisor_stops_the_trainer(tmp_path, monkeypatch):
    sim = Sim(tmp_path, "hang", [(0, Mem(30, 5.0))])
    read = sim.read

    def interrupted():
        if sim.now >= 20:
            raise KeyboardInterrupt
        return read()

    sim.read = interrupted
    with pytest.raises(KeyboardInterrupt):
        sim.run(monkeypatch)
    assert len(sim.attempts()) == 1 and all_gone(sim.attempts())


@posix
def test_caffeinate_holds_the_machine_awake_for_the_life_of_the_process(tmp_path, monkeypatch):
    fake = tmp_path / "caffeinate"
    fake.write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/caffeinate.args\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    ramguard.keep_awake()
    for _ in range(100):
        if (tmp_path / "caffeinate.args").exists():
            break
        time.sleep(0.05)
    assert (tmp_path / "caffeinate.args").read_text().split() == ["-i", "-w", str(os.getpid())]
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    ramguard.keep_awake()   # no caffeinate (Linux): nothing happens


@posix
def test_terminal_signals_end_the_supervisor_but_a_nohup_hangup_is_ignored():
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)   # what nohup does
        ramguard.exit_on_signals()
        assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        with pytest.raises(SystemExit) as stopped:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert stopped.value.code == 128 + signal.SIGTERM
        signal.signal(signal.SIGHUP, signal.SIG_DFL)   # no nohup: closing the terminal must stop the training too
        ramguard.exit_on_signals()
        with pytest.raises(SystemExit):
            signal.getsignal(signal.SIGHUP)(signal.SIGHUP, None)
    finally:
        for s, h in saved.items():
            signal.signal(s, h)
