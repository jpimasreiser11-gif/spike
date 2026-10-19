"""RAM guard and supervisor for LoRA training on a machine that someone else is using.

    nohup training/scripts/train_supervised.sh finance >/dev/null 2>&1 &    # survives the terminal closing
    tail -f training/runs/finance/ramguard.log

Runs `training/train.sh <specialist>` with SPIKE_RESUME=1 on every attempt (training/lora.py then continues from
the latest checkpoint, or starts at iteration 0 when there is none; to start over, delete training/runs/<spec>/adapter/
resume), samples memory every SAMPLE_SEC and stops the training process group (SIGTERM, SIGKILL after GRACE_SEC) when
  - swap in use has grown by more than SWAP_GROWTH_GB since this attempt started, or
  - available memory is below MIN_FREE_GB.
Then it waits until available memory has been at least RESUME_FREE_GB for RESUME_STABLE_MIN minutes in a row and starts
the next attempt (with a new swap baseline); the first attempt waits the same way if less is available at launch. It
gives up (exit 75) after MAX_RESTARTS restarts. When training exits on its own, its exit code is passed through (0 =
finished; a crash is not retried). Every decision is logged with the numbers to training/runs/<specialist>/ramguard.log. Where `caffeinate` exists (macOS) it holds `caffeinate -i` (no idle
sleep) for as long as it runs. "Available" is psutil's: memory that can be given to a process without swapping.

Environment (defaults): SWAP_GROWTH_GB=2  MIN_FREE_GB=2.5  RESUME_FREE_GB=22 (the 20 GB MLX cap plus margin)
RESUME_STABLE_MIN=10  MAX_RESTARTS=20  SAMPLE_SEC=5  GRACE_SEC=30  LOG_EVERY_SEC=300 (status line while idle)
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Self

ROOT = Path(__file__).resolve().parents[1]
GB = 1024**3
GAVE_UP = 75


@dataclass(frozen=True)
class Config:
    swap_growth_gb: float = 2.0
    min_free_gb: float = 2.5
    resume_free_gb: float = 22.0
    resume_stable_min: float = 10.0
    max_restarts: int = 20
    sample_sec: float = 5.0
    grace_sec: float = 30.0
    log_every_sec: float = 300.0

    @classmethod
    def from_env(cls, env) -> Self:
        out = {}
        for f in fields(cls):
            if (raw := env.get(f.name.upper())) not in (None, ""):
                try:
                    out[f.name] = f.type(raw)
                except ValueError:
                    raise SystemExit(f"{f.name.upper()}={raw!r} is not a valid {f.type.__name__}") from None
        return cls(**out)


@dataclass(frozen=True)
class Mem:
    available_gb: float
    swap_gb: float   # swap in use

    def __str__(self) -> str:
        return f"available {self.available_gb:.2f} GB, swap used {self.swap_gb:.2f} GB"


def read_mem() -> Mem:
    import psutil

    return Mem(psutil.virtual_memory().available / GB, psutil.swap_memory().used / GB)


def stop_reason(mem: Mem, swap_base_gb: float, cfg: Config) -> str | None:
    """Why training must stop now, or None."""
    grown = mem.swap_gb - swap_base_gb
    if grown > cfg.swap_growth_gb:
        return f"swap grew {grown:.2f} GB (limit {cfg.swap_growth_gb:g}): {swap_base_gb:.2f} -> {mem.swap_gb:.2f} GB used; {mem}"
    if mem.available_gb < cfg.min_free_gb:
        return f"available memory {mem.available_gb:.2f} GB is below {cfg.min_free_gb:g} GB; {mem}"
    return None


def stable_since(since: float | None, now: float, mem: Mem, cfg: Config) -> float | None:
    """Start of the current unbroken stretch with at least RESUME_FREE_GB available (None: not enough right now)."""
    if mem.available_gb < cfg.resume_free_gb:
        return None
    return now if since is None else since


def may_resume(since: float | None, now: float, cfg: Config) -> bool:
    return since is not None and now - since >= cfg.resume_stable_min * 60


class Log:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
        print(line, file=sys.stderr, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def group_alive(pgid: int) -> bool:
    """Is any live process (a zombie only waits for its parent to reap it) left in the process group?"""
    import psutil

    for p in psutil.process_iter(["status"]):
        try:
            if p.info["status"] != psutil.STATUS_ZOMBIE and os.getpgid(p.pid) == pgid:
                return True
        except (ProcessLookupError, PermissionError):
            pass
    return False


def kill_group(pgid: int, sig) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, sig)


def stop(proc, cfg: Config, log: Log, clock, sleep) -> None:
    """SIGTERM to the training process group (train.sh, tee, python), SIGKILL to what is left after GRACE_SEC."""
    log(f"stopping pid {proc.pid}: SIGTERM, then SIGKILL after {cfg.grace_sec:g} s")
    kill_group(proc.pid, signal.SIGTERM)
    deadline = clock() + cfg.grace_sec
    while (proc.poll() is None or group_alive(proc.pid)) and clock() < deadline:
        sleep(1.0)
    if proc.poll() is None or group_alive(proc.pid):
        log(f"still running after {cfg.grace_sec:g} s: SIGKILL")
        kill_group(proc.pid, signal.SIGKILL)
    proc.wait()


def wait_for_memory(cfg: Config, log: Log, read, clock, sleep) -> None:
    since, beat = None, clock()
    log(f"waiting for {cfg.resume_free_gb:g} GB available for {cfg.resume_stable_min:g} min in a row; {read()}")
    while True:
        sleep(cfg.sample_sec)
        mem, now = read(), clock()
        new = stable_since(since, now, mem, cfg)
        if (new is None) != (since is None):
            log(f"{'enough memory, timer started' if new is not None else 'below the threshold, timer reset'}; {mem}")
        since = new
        if may_resume(since, now, cfg):
            log(f"memory stable for {cfg.resume_stable_min:g} min; {mem}")
            return
        if now - beat >= cfg.log_every_sec:
            log(f"still waiting; {mem}")
            beat = now


def supervise(cmd, run_dir, cfg: Config, *, env=None, read=read_mem, clock=time.monotonic, sleep=time.sleep) -> int:
    """Run `cmd` until it exits by itself (returns its exit code) or MAX_RESTARTS stops have been used (GAVE_UP)."""
    log = Log(Path(run_dir) / "ramguard.log")
    env = {**(os.environ if env is None else env), "SPIKE_RESUME": "1"}
    log(f"supervising {' '.join(map(str, cmd))}; {cfg}")
    proc, stops = None, 0
    try:
        while True:
            mem = read()
            if stops == 0 and mem.available_gb < cfg.resume_free_gb:  # nor start the first attempt on a busy machine
                wait_for_memory(cfg, log, read, clock, sleep)
                mem = read()
            base = mem.swap_gb
            proc = subprocess.Popen(cmd, env=env, start_new_session=True)
            log(f"attempt {stops + 1}: started pid {proc.pid}; {mem}; stop above {base + cfg.swap_growth_gb:.2f} GB swap "
                f"or below {cfg.min_free_gb:g} GB available")
            why, beat = None, clock()
            while why is None:
                sleep(cfg.sample_sec)
                if proc.poll() is not None:
                    break
                mem = read()
                why = stop_reason(mem, base, cfg)
                if why is None and clock() - beat >= cfg.log_every_sec:
                    log(f"attempt {stops + 1} running; {mem}")
                    beat = clock()
            if why is None:
                code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
                log(f"training exited on its own with code {code}; not restarting")
                return code
            log(f"attempt {stops + 1}: STOP, {why}")
            stop(proc, cfg, log, clock, sleep)
            stops += 1
            if stops > cfg.max_restarts:
                log(f"giving up: stopped {stops} times, MAX_RESTARTS={cfg.max_restarts}")
                return GAVE_UP
            wait_for_memory(cfg, log, read, clock, sleep)
            log(f"restart {stops} of at most {cfg.max_restarts}: relaunching with SPIKE_RESUME=1; {read()}")
    finally:
        if proc is not None and (proc.poll() is None or group_alive(proc.pid)):  # the supervisor itself is being stopped
            stop(proc, cfg, log, clock, sleep)


def keep_awake() -> None:
    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # holds the assertion until this process ends


def exit_on_signals() -> None:
    """SIGTERM, SIGINT and SIGHUP end this process (and, through supervise's `finally`, the training); a SIGHUP that
    nohup set to ignored stays ignored."""
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if (sig := getattr(signal, name, None)) and signal.getsignal(sig) is not signal.SIG_IGN:
            signal.signal(sig, lambda n, frame: sys.exit(128 + n))


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0].startswith("-"):
        raise SystemExit("usage: ramguard.py <specialist>   (see the top of this file for the environment variables)")
    keep_awake()
    exit_on_signals()
    cmd = ["bash", str(ROOT / "training" / "train.sh"), args[0]]
    return supervise(cmd, ROOT / "training" / "runs" / args[0], Config.from_env(os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
