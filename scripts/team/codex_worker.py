"""Codex's side of the SPIKE team: takes Codex's tasks from the board on origin/main and has Codex CLI do them, one at a time.

    python scripts/team/codex_worker.py setup --repo ~/Downloads/Spike-codex             # .venv and web/node_modules, once
    nohup python scripts/team/codex_worker.py run --repo ~/Downloads/Spike-codex >/dev/null 2>&1 &    # detached
    python scripts/team/codex_worker.py status                                          # what it is doing, what it did
    python scripts/team/codex_worker.py stop                                            # exit at the next step

--repo is a git worktree or clone used only by Codex. Each pass: `git fetch origin`, read docs/team/tasks.json from
origin/main (not from the working tree), take board.next_task(owner="codex") that was not already pushed for the same board
status and review file, put the branch codex/<id> in place (todo: from origin/main; changes: origin/codex/<id> plus a merge
of origin/main, a conflict is left to the lead), run `codex exec --sandbox workspace-write` with the task as the prompt,
verify outside Codex (ruff, the whole pytest suite, vitest and the build if web/ changed), append the result to the
report docs/team/reports/<ID>.md, commit and `git push -u origin codex/<id>`. It never pushes anything else, never touches
main, never runs reset --hard, clean or checkout -- on the worktree, and deletes nothing outside its state dir.

State dir (default ~/.spike-team): state.json (per task: id, status_on_board, branch, head_sha, pushed_utc, result,
review_sha), worker.log (one UTC line per step), worker.lock (pid; one worker per state dir), STOP (`stop` creates it; the
worker removes it when it exits), prompt-<ID>.md, last-<ID>.md (Codex's last message), codex-<ID>.log. results: ok,
verify_failed, no_changes, failed, rate_limited, conflict, push_failed (network; only the push is retried), push_rejected.

The machine also trains models: before Codex and before each verification command the worker waits (checks every 60 s)
while free RAM (macOS vm_stat free+inactive+speculative; Linux MemAvailable) is below --min-free-gb. STOP is honoured while
idle or waiting, between tasks, never in the middle of one.

Tests replace the verification commands with the environment variable SPIKE_TEAM_VERIFY (one command line, run once
in the repo instead of ruff, pytest, vitest and the build). Exit codes: 0 ok, 1 error (--once), 2 usage (no Codex, not a
git repo), 4 another worker holds the lock, 5 the worktree is dirty (--once; the loop logs it and tries again next poll).
"""

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import board

OWNER = "codex"
GB = 1024**3
STATE_DEFAULT = Path.home() / ".spike-team"
IDENT = ["-c", "user.name=jpimasreiser11-gif", "-c", "user.email=225495977+jpimasreiser11-gif@users.noreply.github.com"]
BACKOFF = (2, 4, 8, 16)   # seconds between the retries of a network operation
NAP_STEP = 5              # a wait is slept in steps this long, looking for STOP between them
MEM_CHECK = 60            # seconds between two readings while waiting for RAM
RATE_WAIT, RATE_WAIT_MAX = 30 * 60, 6 * 3600
VERIFY_TIMEOUT = 3600
SECTION = "## Verificación del trabajador"
SECTION_END = "<!-- fin de la verificación del trabajador -->"   # what a later round replaces ends here
EXIT_ERROR, EXIT_USAGE, EXIT_LOCKED, EXIT_DIRTY = 1, 2, 4, 5
# results that are not worked again while the board shows the same status and the same review file
DONE_RESULTS = {"ok", "verify_failed", "no_changes", "failed", "conflict", "push_rejected"}
RATE_RE = re.compile(r"rate.?limit|usage.?limit|\b429\b|try again", re.I)
REJECTED_RE = re.compile(r"rejected|non-fast-forward|fetch first|protected branch|permission denied|denied to", re.I)
_DURATION = re.compile(r"try again in\s+((?:\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b[\s,]*(?:and\s+)?)+)", re.I)
_PART = re.compile(r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", re.I)
_UNIT = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sleep(seconds: float) -> None:   # the only place that really sleeps; tests replace it
    time.sleep(seconds)


def last_lines(text: str, n: int) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-n:])


# ---- git ---------------------------------------------------------------------------------------------------------

class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, ident: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}   # a missing credential fails instead of waiting on a prompt
    return subprocess.run(["git", *(IDENT if ident else ()), "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def git_out(repo: Path, *args: str, ident: bool = False) -> str:
    cp = git(repo, *args, ident=ident)
    if cp.returncode:
        raise GitError(f"git {' '.join(args)} failed ({cp.returncode}): {(cp.stderr or cp.stdout).strip()}")
    return cp.stdout.strip()


def with_retries(fn, what: str, log) -> tuple[bool, str]:
    """fn() -> (ok, text). A failure is retried 4 times after 2/4/8/16 s, unless it is a rejection (it would repeat)."""
    for delay in (*BACKOFF, None):
        ok, text = fn()
        if ok or delay is None or REJECTED_RE.search(text):
            return ok, text
        log(f"{what} failed ({text.strip().splitlines()[-1] if text.strip() else 'no output'}); retrying in {delay} s")
        _sleep(delay)
    return False, ""   # unreachable


# ---- memory ------------------------------------------------------------------------------------------------------

def parse_vm_stat(text: str) -> float:
    """Free RAM in GB from macOS `vm_stat`: (free + inactive + speculative pages) x page size."""
    size = re.search(r"page size of (\d+) bytes", text)
    pages = {k: re.search(rf"^Pages {k}:\s+(\d+)", text, re.M) for k in ("free", "inactive", "speculative")}
    if not pages["free"]:
        raise ValueError("no 'Pages free' line in the vm_stat output")
    return sum(int(m.group(1)) for m in pages.values() if m) * (int(size.group(1)) if size else 4096) / GB


def parse_meminfo(text: str) -> float:
    """Free RAM in GB from Linux /proc/meminfo: MemAvailable."""
    m = re.search(r"^MemAvailable:\s+(\d+)\s*kB", text, re.M)
    if not m:
        raise ValueError("no MemAvailable line in /proc/meminfo")
    return int(m.group(1)) * 1024 / GB


def free_ram_gb() -> float | None:
    """Free RAM now, or None when this platform cannot say (the guard then does not wait)."""
    try:
        if sys.platform == "darwin":
            return parse_vm_stat(subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=15, check=True).stdout)
        if sys.platform.startswith("linux"):
            return parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


# ---- the lock, the state -----------------------------------------------------------------------------------------

class Locked(Exception):
    pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":   # os.kill(pid, 0) would terminate the process there
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def acquire_lock(state_dir: Path) -> Path:
    """Create worker.lock holding our pid; a lock whose pid is not alive is stale and replaced."""
    lock = state_dir / "worker.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = read_pid(lock)
            try:
                fresh = not pid and time.time() - lock.stat().st_mtime < 5   # created a moment ago, pid not written yet
            except FileNotFoundError:
                continue
            if (pid and pid != os.getpid() and pid_alive(pid)) or fresh:
                raise Locked(f"another worker (pid {pid or '?'}) holds {lock}") from None
            with contextlib.suppress(FileNotFoundError):
                lock.unlink()   # stale
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
        return lock
    raise Locked(f"cannot take {lock}")


class State:
    """state.json: {"tasks": {id: record}, "current": {...} | None, "blocked": "why it cannot start a task"}."""

    def __init__(self, directory: Path):
        self.path = directory / "state.json"
        self.data: dict = {"version": 1, "tasks": {}, "current": None, "blocked": "", "updated_utc": ""}
        if self.path.is_file():
            with contextlib.suppress(ValueError, OSError, TypeError):
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.data["updated_utc"] = utc_now()
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


# ---- prompt, rate limit, verification ----------------------------------------------------------------------------

def build_prompt(task: dict, review: str, branch: str, resumed: bool = False) -> str:
    tid = task["id"]
    lines = [
        "Eres Codex y trabajas en SPIKE; Claude es el líder del proyecto y revisará tu trabajo. "
        "Antes de tocar nada, lee AGENTS.md y docs/team/PLAN.md y síguelos.",
        "",
        f"## Tarea {tid}: {task['title']}",
        "",
        f"- Fase: {task.get('phase') or '-'}",
        f"- Estado en el tablero: {task['status']}",
        f"- Rama de trabajo: {branch}",
        f"- Rutas: {', '.join(task.get('paths', [])) or '-'}",
        "",
        "## Especificación",
        "",
        task["spec"].strip(),
        "",
        "## Criterios de aceptación",
        "",
        *[f"- {a}" for a in task["accept"]],
    ]
    if task["status"] == "changes":
        lines += ["", f"## Revisión de Claude (docs/team/reviews/{tid}.md): corrige lo que pide", "",
                  review.strip() or "(no hay archivo de revisión en origin/main; guíate por la especificación)"]
    if resumed:
        lines += ["", "Nota: el árbol de trabajo ya tiene cambios sin confirmar de un intento anterior que se "
                      "interrumpió (límite de uso). Son tuyos: continúa desde ahí."]
    lines += ["", "## Entrega", "",
              f"- Escribe tu informe en docs/team/reports/{tid}.md, con el formato que describe AGENTS.md.",
              "- No hagas commit ni push: lo hace el trabajador (scripts/team/codex_worker.py).",
              "- El tablero (docs/team/tasks.json) lo gestiona Claude: no lo edites.",
              "- No añadas dependencias nuevas. Escribe pruebas y déjalas en verde."]
    return "\n".join(lines) + "\n"


def rate_limit_wait(text: str) -> int:
    """Seconds to wait after a usage-limit message: 'try again in 2 hours 30 minutes' plus a minute, else 30 minutes."""
    m = _DURATION.search(text)
    secs = sum(int(n) * _UNIT[u[0].lower()] for n, u in _PART.findall(m.group(1))) if m else 0
    return min(secs + 60, RATE_WAIT_MAX) if secs else RATE_WAIT


def venv_exe(repo: Path, name: str) -> Path:
    return repo / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def verify_plan(repo: Path, web_changed: bool) -> list[tuple[str, list[str], str]]:
    """[(command as shown in the report, argv, directory relative to the repo)]."""
    if override := os.environ.get("SPIKE_TEAM_VERIFY"):
        return [(override, shlex.split(override), ".")]
    plan = [(".venv/bin/ruff check .", [str(venv_exe(repo, "ruff")), "check", "."], "."),
            (".venv/bin/python -m pytest -q", [str(venv_exe(repo, "python")), "-m", "pytest", "-q"], ".")]
    if web_changed and (repo / "web" / "node_modules").is_dir():
        plan += [("npx vitest run", ["npx", "vitest", "run"], "web"), ("npm run build", ["npm", "run", "build"], "web")]
    return plan


def run_capture(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    env = {**os.environ, "SPIKE_NO_KEYRING": "1"}   # no keychain prompt on a machine nobody is watching
    try:
        cp = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout:g} s"
    except OSError as e:
        return 127, f"cannot run {argv[0]}: {e}"
    return cp.returncode, cp.stdout


def kill_group(proc: subprocess.Popen) -> None:
    """Stop a process and what it started (Codex runs the tests, shells, ...): TERM, then KILL after 10 s."""
    try:
        if os.name == "nt":
            proc.kill()
            return
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# ---- the worker --------------------------------------------------------------------------------------------------

class Worker:
    def __init__(self, repo: Path, state_dir: Path, codex: str, *, poll: float = 900, min_free_gb: float = 4.0,
                 timeout: float = 10800, once: bool = False, mem_reader=None):
        self.repo, self.dir, self.codex = Path(repo), Path(state_dir), codex
        self.poll, self.min_free_gb, self.timeout, self.once = poll, min_free_gb, timeout, once
        self.mem_reader = mem_reader or free_ram_gb
        self.state = State(self.dir)
        self.stop_file = self.dir / "STOP"
        self.log_file = self.dir / "worker.log"

    # -- small things
    def log(self, msg: str, tid: str = "") -> None:
        line = f"{utc_now()} {f'[{tid}] ' if tid else ''}{msg}"
        with contextlib.suppress(UnicodeEncodeError, OSError):
            print(line, file=sys.stderr, flush=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def stop_requested(self) -> bool:
        return self.stop_file.exists()

    def nap(self, seconds: float) -> bool:
        """Sleep, looking for STOP every few seconds; True if STOP was asked for."""
        left = seconds
        while left > 0:
            if self.stop_requested():
                return True
            step = min(NAP_STEP, left)
            _sleep(step)
            left -= step
        return self.stop_requested()

    def set_current(self, tid: str | None, step: str = "") -> None:
        self.state.data["current"] = {"id": tid, "step": step, "since_utc": utc_now()} if tid else None
        self.state.save()

    def rev(self, ref: str) -> str:
        cp = git(self.repo, "rev-parse", "--verify", "-q", ref)
        return cp.stdout.strip() if cp.returncode == 0 else ""

    def dirty_files(self) -> list[str]:
        return [ln for ln in git_out(self.repo, "status", "--porcelain").splitlines() if ln.strip()]

    def record(self, task: dict, branch: str, result: str, review_sha: str, head: str = "", **extra) -> dict:
        rec = {"id": task["id"], "status_on_board": task["status"], "branch": branch, "head_sha": head or self.rev("HEAD"),
               "pushed_utc": "", "result": result, "review_sha": review_sha, "finished_utc": utc_now(), **extra}
        self.state.data["tasks"][task["id"]] = rec
        self.state.save()
        why = last_lines(str(rec.get("error", "")), 1)[:200]
        self.log(f"result {result}" + (f" head {rec['head_sha'][:10]}" if rec["head_sha"] else "") + (f" ({why})" if why else ""),
                 task["id"])
        return rec

    # -- memory guard
    def wait_for_memory(self, honour_stop: bool = True) -> bool:
        """Wait while free RAM is below --min-free-gb. False only if STOP came during the wait (and is honoured)."""
        logged = False
        while self.min_free_gb > 0:
            free = self.mem_reader()
            if free is None or free >= self.min_free_gb:
                break
            if not logged:
                self.log(f"waiting for RAM: {free:.2f} GB free, need {self.min_free_gb:g} GB (checking every {MEM_CHECK} s)")
                logged = True
            if self.nap(MEM_CHECK) and honour_stop:
                return False
        if logged:
            self.log("enough RAM again")
        return True

    # -- the board on origin/main
    def fetch(self) -> bool:
        ok, text = with_retries(lambda: self._pair("fetch", "origin"), "git fetch origin", self.log)
        if not ok:
            self.log(f"git fetch origin failed: {text.strip()[-300:]}")
        return ok

    def _pair(self, *args: str) -> tuple[bool, str]:
        cp = git(self.repo, *args)
        return cp.returncode == 0, (cp.stderr or cp.stdout)

    def read_board(self) -> dict | None:
        cp = git(self.repo, "show", "origin/main:docs/team/tasks.json")
        if cp.returncode:
            self.log("origin/main has no docs/team/tasks.json yet")
            return None
        try:
            data = board.parse_board(cp.stdout)
        except board.BoardError as e:
            self.log(f"the board on origin/main is unreadable: {e}")
            return None
        if problems := board.validate(data):
            self.log("the board on origin/main is invalid, waiting for the lead to fix it: " + "; ".join(problems[:5]))
            return None
        return data

    def review(self, tid: str) -> tuple[str, str]:
        """(text, blob sha) of docs/team/reviews/<ID>.md on origin/main; ("", "") when there is none."""
        path = f"origin/main:docs/team/reviews/{tid}.md"
        cp = git(self.repo, "show", path)
        return (cp.stdout, self.rev(path)) if cp.returncode == 0 else ("", "")

    def skip_ids(self, data: dict) -> list[str]:
        """Tasks already worked at this board status and review file (nothing newer to answer)."""
        skip = []
        for t in data["tasks"]:
            rec = self.state.data["tasks"].get(t["id"])
            if not rec or rec.get("result") not in DONE_RESULTS or rec.get("status_on_board") != t["status"]:
                continue
            if rec.get("review_sha", "") != (self.review(t["id"])[1] if t["status"] == "changes" else ""):
                continue
            if rec["result"] == "conflict" and (rec.get("main_sha") != self.rev("origin/main")
                                                or rec.get("remote_sha") != self.rev(f"refs/remotes/origin/{rec['branch']}")):
                continue   # main or the branch moved since: the lead may have resolved it
            skip.append(t["id"])
        return skip

    # -- one pass, one task
    def iteration(self) -> str:
        if not self.fetch():
            return "fetch_failed"
        data = self.read_board()
        if data is None:
            return "idle"
        task = board.next_task(data, OWNER, self.skip_ids(data))
        if task is None:
            self.log("no task for codex")
            return "idle"
        return self.run_task(task)

    def run_task(self, task: dict) -> str:
        tid, branch = task["id"], f"codex/{task['id'].lower()}"
        review_text, review_sha = self.review(tid) if task["status"] == "changes" else ("", "")
        self.log(f"task {task['status']}: {task['title']}", tid)
        try:
            return self._run_task(task, branch, review_text, review_sha)
        except Exception as e:
            self.log(f"worker error: {e!r}\n{traceback.format_exc()}", tid)
            with contextlib.suppress(Exception):
                wip = self.park_failed_work(tid)
                self.record(task, branch, "failed", review_sha, error=f"worker error: {e!r}", wip_sha=wip)
            return "worked"
        finally:
            with contextlib.suppress(Exception):
                self.set_current(None)

    def _run_task(self, task: dict, branch: str, review_text: str, review_sha: str) -> str:
        tid = task["id"]
        prev = self.state.data["tasks"].get(tid) or {}
        same = prev.get("status_on_board") == task["status"] and prev.get("review_sha") == review_sha
        # a push that failed on the network: the commit is there, only the push is repeated
        if same and prev.get("result") == "push_failed" and self.rev(f"refs/heads/{branch}") == prev.get("head_sha"):
            self.set_current(tid, "push")
            self.log("retrying the push of the commit already made", tid)
            return self.push_and_record(task, branch, review_sha, prev["pending_result"], prev.get("verify", []),
                                        head=prev["head_sha"])
        resumed = bool(same and prev.get("result") == "rate_limited" and prev.get("branch") == branch
                       and git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD") == branch
                       and self.rev("HEAD") == prev.get("head_sha"))
        if resumed:
            self.log("continuing the work left by the interrupted attempt", tid)
        else:
            if dirty := self.dirty_files():
                why = (f"the worktree {self.repo} has uncommitted changes ({len(dirty)} entries, e.g. {dirty[0].strip()}); "
                       "commit or remove them yourself, the worker never touches them")
                self.state.data["blocked"] = why
                self.state.save()
                self.log("refusing to start: " + why, tid)
                return "dirty"
            self.set_current(tid, "branch")
            if self.prepare_branch(task, branch) == "conflict":
                self.record(task, branch, "conflict", review_sha, main_sha=self.rev("origin/main"),
                            remote_sha=self.rev(f"refs/remotes/origin/{branch}"),
                            error="git merge origin/main conflicts; the lead resolves it")
                return "worked"
        self.state.data["blocked"] = ""
        prompt = self.dir / f"prompt-{tid}.md"
        prompt.write_text(build_prompt(task, review_text, branch, resumed), encoding="utf-8")

        while True:   # one Codex run; a usage limit waits and runs it again on what it left
            self.set_current(tid, "memory")
            if not self.wait_for_memory():
                self.log("stopped while waiting for RAM", tid)
                return "stopped"
            self.set_current(tid, "codex")
            outcome, output = self.run_codex(tid, prompt)
            if outcome != "rate_limited":
                break
            self.record(task, branch, "rate_limited", review_sha, error=last_lines(output, 10))
            wait = rate_limit_wait(output)
            if self.once:
                return "rate_limited"
            prompt.write_text(build_prompt(task, review_text, branch, resumed=True), encoding="utf-8")
            self.log(f"usage limit; waiting {wait // 60} min before running it again", tid)
            self.set_current(tid, "rate_limited")
            if self.nap(wait):
                return "stopped"

        if outcome != "ok":
            wip = self.park_failed_work(tid)
            self.record(task, branch, "failed", review_sha, error=last_lines(output, 40), wip_sha=wip)
            return "worked"
        changed, ahead = self.dirty_files(), self.ahead(branch)
        if not changed and not ahead:
            self.record(task, branch, "no_changes", review_sha)
            return "worked"
        results: list[dict] = []
        if changed:
            self.set_current(tid, "verify")
            results = self.verify(tid)
            self.set_current(tid, "commit")
            git_out(self.repo, "add", "-A")
            git_out(self.repo, "commit", "-m", f"{tid}: {task['title']}", "-m",
                    "Hecho por Codex con el trabajador de equipo (scripts/team/codex_worker.py).", ident=True)
            result = "ok" if all(r["exit"] == 0 for r in results) else "verify_failed"
        else:
            result = "no_changes"   # only the merge of main is new
        self.set_current(tid, "push")
        return self.push_and_record(task, branch, review_sha, result, results)

    def prepare_branch(self, task: dict, branch: str) -> str:
        """Put codex/<id> in place; "conflict" if merging origin/main into the reviewed branch fails (merge aborted)."""
        if task["status"] == "changes":
            if self.rev(f"refs/remotes/origin/{branch}"):
                git_out(self.repo, "checkout", "-q", "-B", branch, "--no-track", f"origin/{branch}")
                if git(self.repo, "merge", "--no-edit", "origin/main", ident=True).returncode:
                    git(self.repo, "merge", "--abort")
                    return "conflict"
                return "ok"
            self.log(f"origin/{branch} does not exist; starting from origin/main", task["id"])
        git_out(self.repo, "checkout", "-q", "-B", branch, "--no-track", "origin/main")
        return "ok"

    def base_ref(self, branch: str) -> str:
        return f"origin/{branch}" if self.rev(f"refs/remotes/origin/{branch}") else "origin/main"

    def ahead(self, branch: str) -> int:
        return int(git_out(self.repo, "rev-list", "--count", f"{self.base_ref(branch)}..HEAD"))

    def park_failed_work(self, tid: str) -> str:
        """Codex failed: what it left becomes a local commit (never pushed) so the worktree is clean for the next task."""
        try:
            if not self.dirty_files():
                return ""
            git_out(self.repo, "add", "-A")
            git_out(self.repo, "commit", "-m", f"WIP {tid}: intento fallido, no se publica", ident=True)
            return self.rev("HEAD")
        except GitError as e:
            self.log(f"could not park the failed attempt: {e}", tid)
            return ""

    # -- Codex
    def run_codex(self, tid: str, prompt: Path) -> tuple[str, str]:
        """-> (ok | failed | rate_limited, what it printed this run)."""
        log_path, last = self.dir / f"codex-{tid}.log", self.dir / f"last-{tid}.md"
        cmd = [self.codex, "exec", "--sandbox", "workspace-write", "-o", str(last), "-"]
        self.log("running: " + " ".join(cmd), tid)
        with open(log_path, "ab") as lf:
            lf.write(f"\n=== {utc_now()} {tid} ===\n".encode())
            lf.flush()
            start = lf.tell()
            try:
                proc = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.PIPE, stdout=lf, stderr=subprocess.STDOUT,
                                        start_new_session=os.name != "nt")
            except OSError as e:
                return "failed", f"cannot start {self.codex}: {e}"
            timed_out = False
            try:
                proc.communicate(prompt.read_bytes(), timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_group(proc)
                proc.wait()
            except BaseException:   # the worker itself is being stopped: do not leave Codex running
                kill_group(proc)
                raise
        output = log_path.read_bytes()[start:].decode("utf-8", errors="replace")
        if timed_out:
            self.log(f"Codex timed out after {self.timeout:g} s", tid)
            return "failed", output + f"\n(timeout after {self.timeout:g} s)"
        self.log(f"Codex exit code {proc.returncode}", tid)
        if proc.returncode == 0:
            return "ok", output
        return ("rate_limited" if RATE_RE.search(output) else "failed"), output

    # -- verification, report, push
    def web_changed(self) -> bool:
        names = git_out(self.repo, "diff", "--name-only", "origin/main").splitlines()
        names += git_out(self.repo, "ls-files", "--others", "--exclude-standard").splitlines()
        return any(n.startswith("web/") for n in names)

    def verify(self, tid: str) -> list[dict]:
        """Run the checks outside Codex and append them to the report; -> [{"cmd", "dir", "exit", "tail"}]."""
        results = []
        for shown, argv, rel in verify_plan(self.repo, self.web_changed()):
            self.wait_for_memory(honour_stop=False)
            self.log(f"verifying: {shown}" + (f" (in {rel})" if rel != "." else ""), tid)
            code, out = run_capture(argv, self.repo / rel, VERIFY_TIMEOUT)
            results.append({"cmd": shown, "dir": rel, "exit": code, "tail": last_lines(out, 15)})
            self.log(f"  exit {code}", tid)
        self.write_report(tid, results)
        return results

    def write_report(self, tid: str, results: list[dict]) -> None:
        report = self.repo / "docs" / "team" / "reports" / f"{tid}.md"
        if report.is_file():
            text = report.read_text(encoding="utf-8")
        else:
            text = f"# Informe {tid}\n\n> Codex no escribió informe para esta tarea; el trabajador creó este archivo.\n"
            last = self.dir / f"last-{tid}.md"
            if last.is_file() and (msg := last.read_text(encoding="utf-8", errors="replace").strip()):
                text += f"\nÚltimo mensaje de Codex:\n\n{msg[:4000]}\n"
        text = re.sub(rf"(?ms)^{re.escape(SECTION)}\n.*?^{re.escape(SECTION_END)}\n?", "", text).rstrip("\n")   # an earlier round's
        parts = [text, "", SECTION, "", f"Ejecutado por el trabajador, fuera de Codex, el {utc_now()}.", ""]
        for r in results:
            where = "" if r["dir"] == "." else f" (en `{r['dir']}/`)"
            parts += [f"### `{r['cmd']}`{where}", "", f"- Código de salida: {r['exit']}", "- Últimas 15 líneas:", "",
                      "```text", r["tail"], "```", ""]
        verdict = "todo en verde" if all(r["exit"] == 0 for r in results) else "ALGO FALLÓ: revisa los códigos de salida"
        parts += [f"Resultado: {verdict}.", "", SECTION_END]
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(parts) + "\n", encoding="utf-8")

    def push_and_record(self, task: dict, branch: str, review_sha: str, result: str, results: list[dict],
                        head: str = "") -> str:
        if not branch.startswith("codex/"):
            raise GitError(f"refusing to push {branch!r}: the worker only pushes codex/* branches")
        ok, text = with_retries(lambda: self._pair("push", "-u", "origin", branch), f"git push origin {branch}", self.log)
        extra = {"verify": [{"cmd": r["cmd"], "exit": r["exit"]} for r in results]}
        if ok:
            rec = self.record(task, branch, result, review_sha, head=head, **extra)
            rec["pushed_utc"] = utc_now()
            self.state.save()
            self.log(f"pushed {branch}", task["id"])
        else:
            self.record(task, branch, "push_rejected" if REJECTED_RE.search(text) else "push_failed", review_sha,
                        head=head, pending_result=result, error=text.strip()[-400:], **extra)
        return "worked"

    # -- the loop
    def run(self) -> int:
        with contextlib.suppress(FileNotFoundError):
            self.stop_file.unlink()   # a STOP left from before this start
        self.log(f"started: repo {self.repo}, codex {self.codex}, poll {self.poll:g} s, once {self.once}")
        code = 0
        while True:
            try:
                outcome = self.iteration()
            except Exception as e:
                self.log(f"pass failed: {e!r}\n{traceback.format_exc()}")
                outcome = "error"
            with contextlib.suppress(Exception):
                self.set_current(None)
            if self.once:
                code = {"dirty": EXIT_DIRTY, "fetch_failed": EXIT_ERROR, "error": EXIT_ERROR}.get(outcome, 0)
                break
            if outcome == "stopped" or self.stop_requested():
                break
            if outcome == "worked":
                continue
            if self.nap(self.poll):
                break
        with contextlib.suppress(FileNotFoundError):
            self.stop_file.unlink()
        self.log(f"exiting with code {code}")
        return code


# ---- commands ----------------------------------------------------------------------------------------------------

def resolve_codex(explicit: str | None) -> str | None:
    """--codex, else $SPIKE_CODEX, else `codex` on PATH; None when none of them runs."""
    for candidate in ([explicit] if explicit else [os.environ.get("SPIKE_CODEX") or "codex"]):
        if found := shutil.which(candidate):
            return found
    return None


def cmd_run(args) -> int:
    codex = resolve_codex(args.codex)
    if not codex:
        what = args.codex or os.environ.get("SPIKE_CODEX") or "codex"
        print(f"error: no encuentro Codex CLI ({what!r}). Instálalo, o indícalo con --codex RUTA o la variable SPIKE_CODEX.",
              file=sys.stderr)
        return EXIT_USAGE
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir() or git(repo, "rev-parse", "--is-inside-work-tree").returncode:
        print(f"error: --repo {repo} is not a git worktree or clone", file=sys.stderr)
        return EXIT_USAGE
    if git(repo, "remote", "get-url", "origin").returncode:
        print(f"error: {repo} has no remote called origin", file=sys.stderr)
        return EXIT_USAGE
    state_dir = Path(args.state).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock = acquire_lock(state_dir)
    except Locked as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_LOCKED
    previous = None
    if os.name != "nt":
        previous = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # the finally below runs; Codex stops with us
    try:
        worker = Worker(repo, state_dir, codex, poll=args.poll, min_free_gb=args.min_free_gb, timeout=args.timeout,
                        once=args.once)
        return worker.run()
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def cmd_status(args) -> int:
    state_dir = Path(args.state).expanduser()
    data = State(state_dir).data
    pid = read_pid(state_dir / "worker.lock")
    running = bool(pid and pid_alive(pid))
    log_file = state_dir / "worker.log"
    tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-5:] if log_file.is_file() else []
    keys = ("status_on_board", "branch", "head_sha", "pushed_utc", "result", "review_sha", "error")
    summary = {"state_dir": str(state_dir), "running": running, "pid": pid if running else None,
               "stop_requested": (state_dir / "STOP").exists(), "current": data.get("current"),
               "blocked": data.get("blocked", ""), "updated_utc": data.get("updated_utc", ""),
               "tasks": {tid: {k: rec[k] for k in keys if rec.get(k)} for tid, rec in data.get("tasks", {}).items()},
               "last_log": tail}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_stop(args) -> int:
    state_dir = Path(args.state).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "STOP").write_text(utc_now() + "\n", encoding="utf-8")
    pid = read_pid(state_dir / "worker.lock")
    if pid and pid_alive(pid):
        print(f"STOP creado: el trabajador (pid {pid}) terminará en el próximo paso; una tarea en curso se acaba antes.")
    else:
        print(f"STOP creado en {state_dir}, pero no hay trabajador en marcha (se borra al arrancar el siguiente).")
    return 0


def setup_steps(repo: Path, python: str | None) -> tuple[list[tuple[str, list[str], Path]], list[str]]:
    """([(what, argv, cwd)], notes about what is already there or cannot be done)."""
    steps, notes = [], []
    if (repo / ".venv").exists():
        notes.append(".venv ya existe: no la toco")
    else:
        py = python or next((p for p in (shutil.which(n) for n in ("python3.13", "python3.12", "python3.11")) if p), None)
        if not py:
            raise ValueError("no encuentro python3.13, python3.12 ni python3.11; indícalo con --python")
        steps.append(("crear .venv", [py, "-m", "venv", str(repo / ".venv")], repo))
        steps.append(('instalar el proyecto: pip install -e ".[dev]"',
                      [str(venv_exe(repo, "python")), "-m", "pip", "install", "-e", ".[dev]"], repo))
    web = repo / "web"
    if (web / "package.json").is_file():
        if (web / "node_modules").exists():
            notes.append("web/node_modules ya existe: no lo toco")
        elif shutil.which("npm"):
            steps.append(("instalar las dependencias de la web: npm ci", ["npm", "ci"], web))
        else:
            notes.append("falta npm: no instalo web/node_modules (la verificación de la web se omite)")
    return steps, notes


def cmd_setup(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"error: {repo} no existe", file=sys.stderr)
        return EXIT_USAGE
    try:
        steps, notes = setup_steps(repo, args.python)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    for note in notes:
        print(note)
    for what, argv, cwd in steps:
        print(f"==> {what}: {' '.join(argv)}", flush=True)
        try:
            code = subprocess.run(argv, cwd=cwd).returncode
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_ERROR
        if code:
            print(f"error: terminó con código {code}", file=sys.stderr)
            return EXIT_ERROR
    print("listo" if steps else "nada que hacer")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codex_worker.py", description="Runs Codex CLI on the Codex tasks of the SPIKE board")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_state(p):
        p.add_argument("--state", default=str(STATE_DEFAULT), help="state directory (default ~/.spike-team)")

    p = sub.add_parser("run", help="take Codex's tasks from origin/main one by one")
    p.add_argument("--repo", required=True, help="the git worktree or clone used only by Codex")
    p.add_argument("--codex", help="Codex CLI (default: $SPIKE_CODEX, then `codex` on PATH)")
    p.add_argument("--once", action="store_true", help="do at most one task and exit")
    p.add_argument("--poll", type=float, default=900, help="seconds between looks at the board when idle (900)")
    add_state(p)
    p.add_argument("--min-free-gb", type=float, default=4.0, help="wait while free RAM is below this (4; 0: never wait)")
    p.add_argument("--timeout", type=float, default=10800, help="kill Codex after this many seconds (10800)")
    add_state(sub.add_parser("status", help="what the worker is doing and what it did"))
    add_state(sub.add_parser("stop", help="ask the worker to exit at its next step"))
    p = sub.add_parser("setup", help="create .venv and web/node_modules in the worktree if missing")
    p.add_argument("--repo", required=True)
    p.add_argument("--python", help="interpreter for the venv (default: python3.13, 3.12 or 3.11)")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "status": cmd_status, "stop": cmd_stop, "setup": cmd_setup}[args.cmd](args)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):   # Spanish text on a console that is not UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
