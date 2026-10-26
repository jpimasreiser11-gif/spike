"""scripts/team: the task board (board.py) and Codex's worker (codex_worker.py).

The board is checked on small JSON boards. The worker runs for real against git repositories in tmp_path (a bare origin, the
lead's clone that edits main, the worker's own clone) with a fake Codex: a small Python script that reads the prompt from
stdin, writes a file, the report and the -o file. No network, no real Codex. The verification commands (ruff, pytest, ...)
are replaced by SPIKE_TEAM_VERIFY, and codex_worker._sleep by a recorder, so nothing waits.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "team"))

import board  # noqa: E402
import codex_worker as cw  # noqa: E402

BOARD_PY = ROOT / "scripts" / "team" / "board.py"
WORKER_PY = ROOT / "scripts" / "team" / "codex_worker.py"
posix = pytest.mark.skipif(sys.platform == "win32", reason="the fake Codex is a #! script and the worker signals process groups")
TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ")


def task(tid: str = "X1", **kw) -> dict:
    t = {"id": tid, "owner": "codex", "status": "todo", "phase": "app", "title": "Skills pack and validators",
         "depends": [], "paths": ["spike/skills/"], "spec": "Build the pack.\n\n- one\n- two",
         "accept": ["pytest passes", "ruff is clean"]}
    return {**t, **kw}


def mk(*tasks: dict) -> dict:
    return {"version": 1, "tasks": list(tasks)}


# ---- the board: validation ---------------------------------------------------------------------------------------

def test_valid_board_has_no_problems():
    b = mk(task("X1"), task("AB12", owner="claude", status="done", depends=[]), task("X2", depends=["X1", "AB12"]))
    assert board.validate(b) == []


@pytest.mark.parametrize("data, needle", [
    (mk(task("X1"), task("X1")), "task X1: duplicate id"),
    (mk(task("X1", owner="robot")), "owner 'robot'"),
    (mk(task("X1", status="finished")), "status 'finished'"),
    (mk(task("x1")), "id 'x1'"),
    (mk(task("ABC1")), "id 'ABC1'"),
    (mk(task("A1234")), "id 'A1234'"),
    (mk(task("X1", depends=["Z9"])), "depends on unknown task 'Z9'"),
    (mk(task("A1", depends=["B1"]), task("B1", depends=["C1"]), task("C1", depends=["A1"])), "dependency cycle: A1 -> B1 -> C1 -> A1"),
    (mk(task("A1", depends=["A1"])), "dependency cycle: A1 -> A1"),
    (mk(task("X1", title="  ")), "title must be a non-empty string"),
    (mk(task("X1", spec="")), "spec must be a non-empty string"),
    (mk(task("X1", accept=[])), "accept must be a non-empty list"),
    (mk(task("X1", accept=["ok", ""])), "accept must be a non-empty list"),
    (mk(task("X1", accept="criterion")), "accept must be a non-empty list"),
    (mk(task("X1", depends="X2")), "depends must be a list of strings"),
    (mk(task("X1", paths=[3])), "paths must be a list of strings"),
    ({"version": 2, "tasks": []}, "version must be 1"),
    ({"version": 1}, '"tasks" must be a list'),
    ([], "must be a JSON object"),
])
def test_validate_reports_each_problem(data, needle):
    assert any(needle in p for p in board.validate(data)), board.validate(data)


def test_validate_lists_every_problem_not_just_the_first():
    problems = board.validate(mk(task("X1", owner="bob"), task("X1", status="nope", depends=["Q1"])))
    assert len(problems) == 4   # bad owner, duplicate id, bad status, unknown dependency


def test_check_command(tmp_path, capsys):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(mk(task("X1"), task("X2"))), encoding="utf-8")
    assert board.main(["check", "--board", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "ok: 2 tasks"
    path.write_text(json.dumps(mk(task("X1"), task("X1", owner="bob"))), encoding="utf-8")
    assert board.main(["check", "--board", str(path)]) == 1
    out = capsys.readouterr().out
    assert "duplicate id" in out and "owner 'bob'" in out
    path.write_text("{not json", encoding="utf-8")
    assert board.main(["check", "--board", str(path)]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert board.main(["check", "--board", str(tmp_path / "missing.json")]) == 1


# ---- the board: next, show ---------------------------------------------------------------------------------------

def test_next_task_takes_changes_before_todo_and_waits_for_dependencies():
    b = mk(task("X1"), task("X2", status="changes"), task("X3", depends=["X1"]),
           task("Y1", owner="claude", status="done"), task("X4", depends=["Y1"]), task("X5", owner="claude"),
           task("X6", status="changes", depends=["X1"]), task("X7", status="doing"))
    assert board.next_task(b, "codex")["id"] == "X2"   # changes first, though X1 comes first in the file
    b["tasks"][1]["status"] = "review"
    assert board.next_task(b, "codex")["id"] == "X1"   # X3 and X6 wait for X1
    b["tasks"][0]["status"] = "done"
    assert board.next_task(b, "codex")["id"] == "X6"   # a changes task whose dependency is done now comes first
    b["tasks"][6]["status"] = "review"
    assert board.next_task(b, "codex")["id"] == "X3"
    assert board.next_task(b, "claude")["id"] == "X5"
    assert board.next_task(b, "joan") is None


def test_next_task_skip_list_and_none():
    b = mk(task("X1"), task("X2"), task("X3", depends=["X1"]), task("Y1", owner="claude", status="done"),
           task("X4", depends=["Y1"]))
    assert board.next_task(b, "codex", skip=["X1"])["id"] == "X2"
    assert board.next_task(b, "codex", skip={"X1", "X2"})["id"] == "X4"   # X3 depends on X1, which is not done
    assert board.next_task(b, "codex", skip=["X1", "X2", "X4"]) is None
    assert board.next_task(mk(), "codex") is None


def test_next_and_show_commands(tmp_path, capsys):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(mk(task("X1", title="Ñandú"), task("X2", status="changes"))), encoding="utf-8")
    assert board.main(["next", "--owner", "codex", "--board", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "X2"
    assert board.main(["next", "--owner", "codex", "--skip", "X2, X1", "--board", str(path)]) == board.NONE_FOUND
    assert capsys.readouterr().out == ""
    assert board.main(["show", "X1", "--board", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Ñandú"
    assert board.main(["show", "Z9", "--board", str(path)]) == 1


def test_next_exits_3_when_nothing_to_do_through_the_real_script(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(mk(task("X1", owner="claude"))), encoding="utf-8")
    r = subprocess.run([sys.executable, str(BOARD_PY), "next", "--owner", "codex", "--board", str(path)],
                       capture_output=True, text=True)
    assert (r.returncode, r.stdout) == (3, "")
    r = subprocess.run([sys.executable, str(BOARD_PY), "next", "--owner", "claude", "--board", str(path)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and json.loads(r.stdout)["id"] == "X1"


# ---- the board: BOARD.md -----------------------------------------------------------------------------------------

def test_render_is_spanish_deterministic_and_grouped_by_phase():
    b = mk(task("X1", phase="app"), task("A1", owner="claude", status="done", phase="base", title="Plan | the board"),
           task("X2", status="review", phase="app", depends=["X1", "A1"]), task("M1", owner="mac", status="blocked", phase="mac"),
           task("J1", owner="joan", status="changes", phase="base"), task("X3", status="doing", phase="app"))
    text = board.render(b)
    assert text == board.render(json.loads(json.dumps(b)))
    assert text.endswith("\n") and not text.endswith("\n\n")
    lines = text.splitlines()
    assert lines[0] == "# Tablero SPIKE"
    assert "python scripts/team/board.py render" in lines[2] and "tasks.json" in lines[2] and "no se edita a mano" in lines[2]
    assert "| Quién | pendiente | en curso | en revisión | cambios pedidos | hecha | bloqueada | total |" in lines
    assert "| Claude | 0 | 0 | 0 | 0 | 1 | 0 | 1 |" in lines
    assert "| Codex | 1 | 1 | 1 | 0 | 0 | 0 | 3 |" in lines
    assert "| Mac | 0 | 0 | 0 | 0 | 0 | 1 | 1 |" in lines
    assert "| joan | 0 | 0 | 0 | 1 | 0 | 0 | 1 |" in lines
    assert "| **Total** | **1** | **1** | **1** | **1** | **1** | **1** | **6** |" in lines
    assert [ln for ln in lines if ln.startswith("## ")] == ["## Resumen", "## Fase: app", "## Fase: base", "## Fase: mac"]
    assert text.count("| ID | Quién | Estado | Tarea | Depende de |") == 3
    assert "| X2 | Codex | en revisión | Skills pack and validators | X1, A1 |" in lines
    assert "| A1 | Claude | hecha | Plan \\| the board | - |" in lines   # a pipe in a title does not break the table
    assert "| M1 | Mac | bloqueada | Skills pack and validators | - |" in lines
    assert "| J1 | joan | cambios pedidos | Skills pack and validators | - |" in lines
    assert text.index("| X1 |") < text.index("| X2 |") < text.index("| X3 |") < text.index("| A1 |")   # phases keep file order


def test_render_command_writes_next_to_the_board_and_check_detects_drift(tmp_path, capsys):
    path = tmp_path / "docs" / "team" / "tasks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(mk(task("X1"), task("X2", status="done"))), encoding="utf-8")
    out = path.with_name("BOARD.md")
    assert board.main(["render", "--check", "--board", str(path)]) == 1   # nothing written yet
    assert "out of date" in capsys.readouterr().err
    assert board.main(["render", "--board", str(path)]) == 0
    assert out.read_text(encoding="utf-8") == board.render(board.load_board(path))
    assert board.main(["render", "--check", "--board", str(path)]) == 0
    assert board.main(["render", "--check", "--board", str(path)]) == 0   # --check writes nothing
    out.write_bytes(out.read_bytes().replace(b"\n", b"\r\n"))   # a Windows checkout of the same text is not drift
    assert board.main(["render", "--check", "--board", str(path)]) == 0
    out.write_text(out.read_text(encoding="utf-8") + "edited by hand\n", encoding="utf-8")
    assert board.main(["render", "--check", "--board", str(path)]) == 1
    path.write_text(json.dumps(mk(task("X1", status="done"), task("X2", status="done"))), encoding="utf-8")
    assert board.main(["render", "--board", str(path)]) == 0   # render rewrites it
    assert board.main(["render", "--check", "--board", str(path)]) == 0
    custom = tmp_path / "elsewhere" / "B.md"
    assert board.main(["render", "--board", str(path), "--out", str(custom)]) == 0 and custom.is_file()
    path.write_text(json.dumps(mk(task("X1", owner="bob"))), encoding="utf-8")
    assert board.main(["render", "--board", str(path)]) == 1   # an invalid board is not rendered
    assert board.main(["render", "--check", "--board", str(path)]) == 1


# ---- the worker's small pure parts -------------------------------------------------------------------------------

def test_parse_vm_stat_sums_free_inactive_and_speculative_pages():
    sample = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               20000.
Pages active:                            400000.
Pages inactive:                          300000.
Pages speculative:                         5000.
Pages throttled:                              0.
Pages wired down:                        150000.
"""
    assert cw.parse_vm_stat(sample) == pytest.approx(325000 * 16384 / 1024**3)
    assert cw.parse_vm_stat(sample.replace("page size of 16384", "page size of 4096")) == pytest.approx(325000 * 4096 / 1024**3)
    with pytest.raises(ValueError):
        cw.parse_vm_stat("vm_stat: command not found")


def test_parse_meminfo_reads_mem_available():
    sample = "MemTotal:       16384000 kB\nMemFree:          200000 kB\nMemAvailable:    8388608 kB\nBuffers:  1 kB\n"
    assert cw.parse_meminfo(sample) == pytest.approx(8.0)
    with pytest.raises(ValueError):
        cw.parse_meminfo("MemTotal: 1 kB\n")
    free = cw.free_ram_gb()
    assert free is None or free > 0   # whatever this machine is


def test_wait_for_memory_logs_once_and_waits_until_enough(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(cw, "_sleep", sleeps.append)
    readings = iter([1.0, 2.5, 3.9, 4.0])
    w = cw.Worker(tmp_path, tmp_path, "codex", min_free_gb=4, mem_reader=lambda: next(readings))
    assert w.wait_for_memory() is True
    assert sum(sleeps) == 3 * cw.MEM_CHECK   # three low readings, a check every 60 s
    log = (tmp_path / "worker.log").read_text(encoding="utf-8")
    assert log.count("waiting for RAM") == 1 and "1.00 GB free, need 4 GB" in log and "enough RAM again" in log
    assert all(TIME.match(line) for line in log.splitlines())
    assert cw.Worker(tmp_path, tmp_path, "codex", min_free_gb=4, mem_reader=lambda: None).wait_for_memory() is True   # unknown: no wait
    assert cw.Worker(tmp_path, tmp_path, "codex", min_free_gb=0, mem_reader=lambda: 0.1).wait_for_memory() is True


def test_wait_for_memory_gives_up_when_stop_is_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "_sleep", lambda s: (tmp_path / "STOP").write_text("x"))   # STOP arrives while waiting
    w = cw.Worker(tmp_path, tmp_path, "codex", min_free_gb=4, mem_reader=lambda: 0.5)
    assert w.wait_for_memory() is False
    assert cw.Worker(tmp_path, tmp_path, "codex", min_free_gb=4, mem_reader=iter([0.5, 9]).__next__).wait_for_memory(honour_stop=False)


def test_rate_limit_wait_reads_a_duration_or_uses_thirty_minutes():
    assert cw.rate_limit_wait("You've hit your usage limit. Try again in 2 hours 30 minutes.") == 2 * 3600 + 30 * 60 + 60
    assert cw.rate_limit_wait("rate limit reached, try again in 45 min") == 45 * 60 + 60
    assert cw.rate_limit_wait("try again in 1 day 4 hours") == cw.RATE_WAIT_MAX   # capped: it asks again after 6 hours
    assert cw.rate_limit_wait("try again in 20 seconds") == 80
    assert cw.rate_limit_wait("You've hit your usage limit. Try again at 3:45 PM.") == cw.RATE_WAIT   # not parsed: 30 min
    assert cw.rate_limit_wait("HTTP 429") == 30 * 60


def test_with_retries_backs_off_2_4_8_16_but_not_on_a_rejection(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cw, "_sleep", sleeps.append)
    calls = []

    def always_down():
        calls.append(1)
        return False, "fatal: unable to access: Could not resolve host"

    assert cw.with_retries(always_down, "git fetch", lambda m: None)[0] is False
    assert (len(calls), sleeps) == (5, [2, 4, 8, 16])   # the try and four retries
    sleeps.clear()
    answers = iter([(False, "network down"), (False, "network down"), (True, "")])
    assert cw.with_retries(lambda: next(answers), "git push", lambda m: None) == (True, "")
    assert sleeps == [2, 4]
    sleeps.clear()
    ok, text = cw.with_retries(lambda: (False, "! [rejected] x -> x (non-fast-forward)"), "git push", lambda m: None)
    assert not ok and sleeps == []   # retrying would give the same answer


def test_prompt_carries_the_task_the_rules_and_for_changes_the_review():
    t = task("X1", status="changes", paths=["a/", "b.py"])
    text = cw.build_prompt(t, "Falta el caso vacío.\nUsa `--strict`.", "codex/x1")
    for needle in ("Codex", "Claude", "AGENTS.md", "docs/team/PLAN.md", "Tarea X1: Skills pack and validators", "Build the pack.",
                   "- pytest passes", "- ruff is clean", "a/, b.py", "Falta el caso vacío.", "docs/team/reports/X1.md",
                   "No hagas commit ni push", "codex/x1"):
        assert needle in text, needle
    todo = cw.build_prompt(task("X1"), "", "codex/x1")
    assert "Revisión de Claude" not in todo and "intento anterior" not in todo
    assert "intento anterior" in cw.build_prompt(task("X1"), "", "codex/x1", resumed=True)


def test_lock_is_taken_once_and_a_dead_pid_is_stale(tmp_path):
    lock = cw.acquire_lock(tmp_path)
    assert read_int(lock) == os.getpid()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock.write_text(f"{sleeper.pid}\n", encoding="utf-8")
        assert cw.pid_alive(sleeper.pid)
        with pytest.raises(cw.Locked, match=str(sleeper.pid)):
            cw.acquire_lock(tmp_path)
    finally:
        sleeper.kill()
        sleeper.wait()
    assert not cw.pid_alive(sleeper.pid)
    assert read_int(cw.acquire_lock(tmp_path)) == os.getpid()   # the stale lock is replaced
    lock.write_text("not a pid\n", encoding="utf-8")
    os.utime(lock, (0, 0))   # old and unreadable: stale too
    assert read_int(cw.acquire_lock(tmp_path)) == os.getpid()


def read_int(path: Path) -> int:
    return int(path.read_text(encoding="utf-8"))


# ---- the worker against real git repositories --------------------------------------------------------------------

FAKE_CODEX = r'''#!@PY@
import json, os, re, sys, time
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
calls = Path(os.environ["FAKE_CODEX_DIR"])
n = len(list(calls.glob("prompt-*.md"))) + 1
(calls / f"prompt-{n}.md").write_text(prompt, encoding="utf-8")
(calls / f"args-{n}.json").write_text(json.dumps({"args": args, "cwd": os.getcwd()}), encoding="utf-8")
(calls / f"pid-{n}").write_text(str(os.getpid()), encoding="utf-8")
tid = re.search(r"## Tarea (\w+):", prompt).group(1)
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
out = Path(args[args.index("-o") + 1])
if mode == "ratelimit":
    Path(f"partial-{tid}.txt").write_text("half done\n", encoding="utf-8")
    print("stream disconnected, retrying", file=sys.stderr)
    print("You've hit your usage limit. Try again in 2 hours 30 minutes.", file=sys.stderr)
    sys.exit(1)
if mode == "fail":
    Path(f"partial-{tid}.txt").write_text("broken\n", encoding="utf-8")
    print("boom: something broke")
    sys.exit(3)
if mode == "sleep":
    time.sleep(60)
out.write_text(f"{tid} done\n", encoding="utf-8")
if mode == "nochange":
    sys.exit(0)
Path(f"feature-{tid}.txt").write_text(f"{tid} v{n}\n", encoding="utf-8")
if mode != "noreport":
    report = Path(f"docs/team/reports/{tid}.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():   # a second round edits the report it finds, the worker's old section included
        report.write_text(report.read_text(encoding="utf-8") + f"\nSegunda ronda (llamada {n}).\n", encoding="utf-8")
    else:
        report.write_text(f"# Informe {tid}\n\nHecho por el falso Codex (llamada {n}).\n", encoding="utf-8")
print("all good")
'''


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=lead", "-c", "user.email=lead@example.com", "-C", str(cwd), *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


class Team:
    """A bare origin, the lead's clone (edits main), the worker's clone, and the fake Codex."""

    def __init__(self, root: Path, tasks: list[dict]):
        self.origin, self.boss, self.repo = root / "origin.git", root / "boss", root / "codex-repo"
        self.state, self.calls, self.codex = root / "state", root / "calls", root / "fake-codex"
        self.calls.mkdir()
        self.codex.write_text(FAKE_CODEX.replace("@PY@", sys.executable), encoding="utf-8")
        self.codex.chmod(0o755)
        git(root, "init", "-q", "--bare", "--initial-branch=main", str(self.origin))
        git(root, "clone", "-q", str(self.origin), str(self.boss))
        git(self.boss, "symbolic-ref", "HEAD", "refs/heads/main")
        self.lead_commit(tasks, {"AGENTS.md": "Reglas del equipo.\n", "docs/team/PLAN.md": "El plan.\n"}, "seed")
        git(root, "clone", "-q", str(self.origin), str(self.repo))

    def lead_commit(self, tasks: list[dict] | None = None, files: dict[str, str] | None = None, msg: str = "lead") -> None:
        """What Claude does: change the board and add files on main."""
        files = dict(files or {})
        if tasks is not None:
            files["docs/team/tasks.json"] = json.dumps(mk(*tasks), indent=2)
        for rel, content in files.items():
            path = self.boss / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        git(self.boss, "add", "-A")
        git(self.boss, "commit", "-q", "-m", msg)
        git(self.boss, "push", "-q", "origin", "main")

    def run(self, *extra: str, once: bool = True) -> int:
        args = ["run", "--repo", str(self.repo), "--codex", str(self.codex), "--state", str(self.state), "--min-free-gb", "0"]
        return cw.main([*args, *(["--once"] if once else []), *extra])

    def sha(self, ref: str) -> str:
        r = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "--verify", "-q", ref], capture_output=True, text=True)
        return r.stdout.strip()

    def show(self, ref: str, path: str) -> str:
        return git(self.origin, "show", f"{ref}:{path}")

    def record(self, tid: str = "X1") -> dict:
        return json.loads((self.state / "state.json").read_text(encoding="utf-8"))["tasks"][tid]

    def prompts(self) -> list[str]:
        files = sorted(self.calls.glob("prompt-*.md"), key=lambda p: int(p.stem.split("-")[1]))
        return [p.read_text(encoding="utf-8") for p in files]

    def log(self) -> str:
        return (self.state / "worker.log").read_text(encoding="utf-8")


@pytest.fixture
def team(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)   # nothing from the machine's git configuration
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("FAKE_CODEX_DIR", str(tmp_path / "calls"))
    monkeypatch.delenv("FAKE_CODEX_MODE", raising=False)
    monkeypatch.setenv("SPIKE_TEAM_VERIFY", shlex.join([sys.executable, "-c", "print('verify ok')"]))
    monkeypatch.setattr(cw, "_sleep", lambda seconds: None)
    return Team(tmp_path, [task("X1")])


@posix
def test_once_on_a_todo_task_pushes_its_branch_and_never_touches_main(team):
    main_before = team.sha("refs/heads/main")
    assert team.run() == 0
    assert team.sha("refs/heads/main") == main_before   # never pushes main
    assert team.sha("refs/heads/codex/x1")
    assert git(team.origin, "for-each-ref", "--format=%(refname)", "refs/heads").split() == ["refs/heads/codex/x1", "refs/heads/main"]
    assert team.show("codex/x1", "feature-X1.txt") == "X1 v1"
    report = team.show("codex/x1", "docs/team/reports/X1.md")
    assert "Hecho por el falso Codex" in report
    assert "## Verificación del trabajador" in report and "- Código de salida: 0" in report and "verify ok" in report
    assert "todo en verde" in report
    for fmt, want in (("%s", "X1: Skills pack and validators"),
                      ("%b", "Hecho por Codex con el trabajador de equipo (scripts/team/codex_worker.py)."),
                      ("%an <%ae>", "jpimasreiser11-gif <225495977+jpimasreiser11-gif@users.noreply.github.com>"),
                      ("%cn <%ce>", "jpimasreiser11-gif <225495977+jpimasreiser11-gif@users.noreply.github.com>")):
        assert git(team.origin, "log", "-1", f"--format={fmt}", "codex/x1") == want
    assert git(team.origin, "rev-list", "--count", "main..codex/x1") == "1"
    rec = team.record()
    assert (rec["id"], rec["status_on_board"], rec["branch"], rec["result"], rec["review_sha"]) == ("X1", "todo", "codex/x1", "ok", "")
    assert rec["head_sha"] == team.sha("refs/heads/codex/x1") and TIME.match(rec["pushed_utc"] + " ")
    call = json.loads((team.calls / "args-1.json").read_text(encoding="utf-8"))
    assert call["args"] == ["exec", "--sandbox", "workspace-write", "-o", str(team.state / "last-X1.md"), "-"]
    assert Path(call["cwd"]).resolve() == team.repo.resolve()
    prompt = team.prompts()[0]
    assert "AGENTS.md" in prompt and "docs/team/PLAN.md" in prompt and "Build the pack." in prompt and "- ruff is clean" in prompt
    assert (team.state / "prompt-X1.md").read_text(encoding="utf-8") == prompt
    assert (team.state / "last-X1.md").read_text(encoding="utf-8") == "X1 done\n"
    assert "all good" in (team.state / "codex-X1.log").read_text(encoding="utf-8")
    log = team.log().splitlines()
    assert log and all(TIME.match(line) for line in log)
    assert any("result ok" in line for line in log) and any("pushed codex/x1" in line for line in log)
    assert not (team.state / "worker.lock").exists() and json.loads((team.state / "state.json").read_text())["current"] is None


@posix
def test_pushed_task_is_skipped_until_a_review_and_changes_land_on_main(team):
    assert team.run() == 0
    first = team.sha("refs/heads/codex/x1")
    assert team.run() == 0 and len(team.prompts()) == 1   # same status, no review: nothing to answer
    assert team.sha("refs/heads/codex/x1") == first
    team.lead_commit([task("X1", status="review")], msg="reviewing")
    assert team.run() == 0 and len(team.prompts()) == 1   # in review: nothing for Codex

    review = "Falta el caso vacío.\n\nUsa `--strict` como pide el plan.\n"
    team.lead_commit([task("X1", status="changes")], {"docs/team/reviews/X1.md": review}, "review X1")
    assert team.run() == 0
    assert len(team.prompts()) == 2
    prompt = team.prompts()[1]
    assert review.strip() in prompt and "Revisión de Claude" in prompt and "Estado en el tablero: changes" in prompt
    second = team.sha("refs/heads/codex/x1")
    assert second != first
    assert git(team.origin, "merge-base", "--is-ancestor", first, second) == ""   # the push is a fast-forward of the first
    assert git(team.origin, "merge-base", "--is-ancestor", team.sha("refs/heads/main"), second) == ""   # main was merged in
    assert team.show("codex/x1", "docs/team/reviews/X1.md") == review.strip()
    assert team.show("codex/x1", "feature-X1.txt") == "X1 v2"
    report = team.show("codex/x1", "docs/team/reports/X1.md")
    assert report.count("## Verificación del trabajador") == 1 and "Segunda ronda (llamada 2)." in report   # old section replaced
    assert report.index("Segunda ronda") < report.index("## Verificación del trabajador")
    rec = team.record()
    assert rec["status_on_board"] == "changes" and rec["result"] == "ok" and rec["head_sha"] == second
    assert rec["review_sha"] == git(team.origin, "rev-parse", "main:docs/team/reviews/X1.md")

    assert team.run() == 0 and len(team.prompts()) == 2   # answered: skipped again
    team.lead_commit(None, {"docs/team/reviews/X1.md": review + "\nUna cosa más.\n"}, "review X1 again")
    assert team.run() == 0 and len(team.prompts()) == 3   # a newer review file, same status: picked again
    assert "Una cosa más." in team.prompts()[2]
    assert team.sha("refs/heads/main") == git(team.boss, "rev-parse", "HEAD")   # main is only ever moved by the lead


@posix
def test_usage_limit_commits_nothing_and_the_next_run_continues_the_same_work(team, monkeypatch):
    main_sha = team.sha("refs/heads/main")
    monkeypatch.setenv("FAKE_CODEX_MODE", "ratelimit")
    assert team.run() == 0
    rec = team.record()
    assert rec["result"] == "rate_limited" and "usage limit" in rec["error"] and rec["pushed_utc"] == ""
    assert git(team.repo, "rev-parse", "HEAD") == main_sha   # nothing committed
    assert team.sha("refs/heads/codex/x1") == ""   # nothing pushed
    assert git(team.repo, "status", "--porcelain") == "?? partial-X1.txt"   # what Codex had done stays for the next attempt
    monkeypatch.setenv("FAKE_CODEX_MODE", "ok")
    assert team.run() == 0   # the dirty tree is our own interrupted work, not somebody's: resumed in place
    assert "intento anterior" in team.prompts()[1]
    assert team.record()["result"] == "ok"
    assert team.show("codex/x1", "partial-X1.txt") == "half done" and team.show("codex/x1", "feature-X1.txt") == "X1 v2"
    assert team.sha("refs/heads/main") == main_sha


@posix
def test_usage_limit_in_the_loop_sleeps_and_retries_until_stopped(team, monkeypatch):
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            (team.state / "STOP").write_text("x", encoding="utf-8")   # `stop` while it waits

    monkeypatch.setattr(cw, "_sleep", sleeper)
    monkeypatch.setenv("FAKE_CODEX_MODE", "ratelimit")
    assert team.run(once=False) == 0
    assert sleeps == [cw.NAP_STEP] * 3   # it waits in short steps, looking for STOP
    assert len(team.prompts()) == 1 and team.record()["result"] == "rate_limited"
    assert "waiting 151 min" in team.log() and team.sha("refs/heads/codex/x1") == ""
    assert not (team.state / "STOP").exists() and not (team.state / "worker.lock").exists()


@posix
def test_a_failed_codex_run_is_recorded_parked_locally_and_not_retried(team, monkeypatch):
    team.lead_commit([task("X1"), task("X2", title="Second one")], msg="two tasks")
    monkeypatch.setenv("FAKE_CODEX_MODE", "fail")
    assert team.run() == 0
    rec = team.record("X1")
    assert rec["result"] == "failed" and "boom: something broke" in rec["error"] and rec["pushed_utc"] == ""
    assert team.sha("refs/heads/codex/x1") == ""
    assert git(team.repo, "status", "--porcelain") == ""   # the worktree is clean for the next task
    assert git(team.repo, "log", "-1", "--format=%s", "codex/x1").startswith("WIP X1")
    assert rec["wip_sha"] == git(team.repo, "rev-parse", "codex/x1")
    monkeypatch.setenv("FAKE_CODEX_MODE", "ok")
    assert team.run() == 0   # moves on to X2
    assert len(team.prompts()) == 2 and "Tarea X2: Second one" in team.prompts()[1]
    assert team.sha("refs/heads/codex/x2") and team.sha("refs/heads/codex/x1") == ""
    assert team.run() == 0 and len(team.prompts()) == 2   # X1 is not tried again: the board did not change


@posix
def test_codex_is_killed_after_the_timeout(team, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "sleep")
    assert team.run("--timeout", "1") == 0
    rec = team.record()
    assert rec["result"] == "failed" and "timeout after 1 s" in rec["error"]
    assert team.sha("refs/heads/codex/x1") == ""


@posix
def test_failing_verification_is_still_committed_and_pushed_but_recorded(team, monkeypatch):
    monkeypatch.setenv("SPIKE_TEAM_VERIFY", shlex.join([sys.executable, "-c", "print('1 failed, 9 passed'); raise SystemExit(1)"]))
    assert team.run() == 0
    rec = team.record()
    assert rec["result"] == "verify_failed" and rec["pushed_utc"] and rec["verify"][0]["exit"] == 1
    report = team.show("codex/x1", "docs/team/reports/X1.md")
    assert "- Código de salida: 1" in report and "1 failed, 9 passed" in report and "ALGO FALLÓ" in report
    assert team.show("codex/x1", "feature-X1.txt") == "X1 v1"
    assert team.run() == 0 and len(team.prompts()) == 1   # pushed: skipped like any other


@posix
def test_report_is_created_with_a_note_when_codex_wrote_none(team, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "noreport")
    assert team.run() == 0
    report = team.show("codex/x1", "docs/team/reports/X1.md")
    assert report.startswith("# Informe X1") and "Codex no escribió informe" in report and "X1 done" in report
    assert "## Verificación del trabajador" in report


@posix
def test_no_changes_is_recorded_and_nothing_is_pushed(team, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "nochange")
    assert team.run() == 0
    assert team.record()["result"] == "no_changes" and team.record()["pushed_utc"] == ""
    assert team.sha("refs/heads/codex/x1") == ""
    assert team.run() == 0 and len(team.prompts()) == 1


@posix
def test_a_merge_conflict_is_aborted_recorded_and_left_to_the_lead(team):
    assert team.run() == 0
    pushed = team.sha("refs/heads/codex/x1")
    team.lead_commit([task("X1", status="changes")], {"feature-X1.txt": "the lead's own version\n",
                                                      "docs/team/reviews/X1.md": "Rehazlo.\n"}, "conflicting change")
    assert team.run() == 0
    rec = team.record()
    assert rec["result"] == "conflict" and rec["status_on_board"] == "changes" and "conflicts" in rec["error"]
    assert len(team.prompts()) == 1   # Codex was not asked to resolve it
    assert git(team.repo, "status", "--porcelain") == "" and not (team.repo / ".git" / "MERGE_HEAD").exists()
    assert team.sha("refs/heads/codex/x1") == pushed
    assert team.run() == 0 and len(team.prompts()) == 1   # skipped while neither main nor the branch moved
    team.lead_commit(None, {"NOTES.md": "something else\n"}, "main moves on")   # now it may be worth a look again
    assert team.run() == 0 and team.record()["result"] == "conflict" and len(team.prompts()) == 1


@posix
def test_dirty_worktree_is_refused_and_left_alone(team, capsys, monkeypatch):
    (team.repo / "scratch.txt").write_text("the owner's own work\n", encoding="utf-8")
    (team.repo / "AGENTS.md").write_text("edited\n", encoding="utf-8")
    assert team.run() == cw.EXIT_DIRTY
    assert team.prompts() == [] and team.sha("refs/heads/codex/x1") == ""
    assert (team.repo / "scratch.txt").read_text(encoding="utf-8") == "the owner's own work\n"
    assert (team.repo / "AGENTS.md").read_text(encoding="utf-8") == "edited\n"
    assert "uncommitted changes" in json.loads((team.state / "state.json").read_text())["blocked"]
    assert "refusing to start" in team.log()
    assert cw.main(["status", "--state", str(team.state)]) == 0
    assert "uncommitted changes" in json.loads(capsys.readouterr().out)["blocked"]
    # in the loop the same thing is logged and tried again at the next look, not fatal
    monkeypatch.setattr(cw, "_sleep", lambda s: (team.state / "STOP").write_text("x", encoding="utf-8"))
    assert team.run(once=False) == 0 and team.prompts() == []
    assert (team.repo / "scratch.txt").exists()


@posix
def test_missing_codex_exits_2(team, tmp_path, monkeypatch, capsys):
    real_path = os.environ["PATH"]
    monkeypatch.delenv("SPIKE_CODEX", raising=False)
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))   # no codex anywhere
    args = ["run", "--repo", str(team.repo), "--state", str(team.state), "--once"]
    assert cw.main(args) == 2
    assert "Codex CLI" in capsys.readouterr().err
    assert cw.main([*args, "--codex", str(tmp_path / "no-such-codex")]) == 2
    assert cw.resolve_codex(None) is None
    monkeypatch.setenv("PATH", real_path)   # git is needed from here on
    monkeypatch.setenv("SPIKE_CODEX", str(team.codex))   # the environment variable is the second choice
    assert cw.main([*args, "--min-free-gb", "0"]) == 0
    monkeypatch.setenv("SPIKE_CODEX", str(tmp_path / "wrong"))
    assert cw.main([*args, "--codex", str(team.codex), "--min-free-gb", "0"]) == 0   # --codex beats the variable
    assert len(team.prompts()) == 1


@posix
def test_codex_found_on_path(team, tmp_path, monkeypatch):
    monkeypatch.delenv("SPIKE_CODEX", raising=False)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy(team.codex, bindir / "codex")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    assert cw.resolve_codex(None) == str(bindir / "codex")


@posix
def test_not_a_git_repo_exits_2(team, tmp_path):
    assert cw.main(["run", "--repo", str(tmp_path / "nowhere"), "--codex", str(team.codex), "--state", str(team.state), "--once"]) == 2
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cw.main(["run", "--repo", str(plain), "--codex", str(team.codex), "--state", str(team.state), "--once"]) == 2


@posix
def test_second_worker_on_the_same_state_dir_is_refused(team, capsys):
    team.state.mkdir()
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (team.state / "worker.lock").write_text(f"{holder.pid}\n", encoding="utf-8")
        assert team.run() == cw.EXIT_LOCKED
        assert str(holder.pid) in capsys.readouterr().err and team.prompts() == []
        assert (team.state / "worker.lock").read_text(encoding="utf-8").strip() == str(holder.pid)   # not taken over
    finally:
        holder.kill()
        holder.wait()
    assert team.run() == 0 and len(team.prompts()) == 1   # its pid is dead now: the lock was stale
    assert not (team.state / "worker.lock").exists()


@posix
def test_stop_and_status_commands(team, capsys, monkeypatch):
    assert cw.main(["status", "--state", str(team.state)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["running"] is False and status["tasks"] == {} and status["stop_requested"] is False
    assert team.run() == 0
    capsys.readouterr()
    assert cw.main(["status", "--state", str(team.state)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["tasks"]["X1"]["result"] == "ok" and status["tasks"]["X1"]["branch"] == "codex/x1" and status["current"] is None
    assert status["last_log"] and status["updated_utc"]

    assert cw.main(["stop", "--state", str(team.state)]) == 0
    assert (team.state / "STOP").is_file() and "no hay trabajador" in capsys.readouterr().out
    assert cw.main(["status", "--state", str(team.state)]) == 0 and json.loads(capsys.readouterr().out)["stop_requested"] is True

    # a loop with nothing to do sleeps in steps; STOP (made while it sleeps) ends it and is removed
    team.lead_commit([task("X1", status="done")], msg="all done")
    seen = []

    def sleeper(seconds):
        seen.append(seconds)
        assert not (team.state / "STOP").exists()   # a STOP left from before the start was cleared at the start
        (team.state / "STOP").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cw, "_sleep", sleeper)
    assert team.run("--poll", "900", once=False) == 0
    assert seen == [cw.NAP_STEP] and not (team.state / "STOP").exists()
    assert len(team.prompts()) == 1 and "no task for codex" in team.log()


@posix
def test_nothing_is_done_while_the_board_is_missing_invalid_or_has_no_codex_task(team):
    git(team.boss, "rm", "-q", "docs/team/tasks.json")
    git(team.boss, "commit", "-q", "-m", "no board")
    git(team.boss, "push", "-q", "origin", "main")
    assert team.run() == 0 and "no docs/team/tasks.json" in team.log()
    team.lead_commit(None, {"docs/team/tasks.json": "{broken"}, "broken")
    assert team.run() == 0 and "unreadable" in team.log()
    team.lead_commit([task("X1", owner="bob")], msg="invalid")
    assert team.run() == 0 and "invalid, waiting for the lead" in team.log()
    team.lead_commit([task("X1", owner="claude"), task("X2", owner="mac")], msg="other people's work")
    assert team.run() == 0
    assert team.prompts() == [] and team.sha("refs/heads/codex/x1") == ""


@posix
def test_the_board_is_read_from_origin_main_not_from_the_working_tree(team):
    git(team.repo, "checkout", "-q", "-b", "elsewhere")
    git(team.repo, "rm", "-q", "docs/team/tasks.json")
    git(team.repo, "commit", "-q", "-m", "local edit of the board")   # the local copy has no tasks at all
    assert team.run() == 0 and len(team.prompts()) == 1
    assert team.sha("refs/heads/codex/x1")


@posix
def test_fetch_failure_is_retried_with_backoff_then_reported(team, monkeypatch):
    sleeps = []
    monkeypatch.setattr(cw, "_sleep", sleeps.append)
    git(team.repo, "remote", "set-url", "origin", str(team.repo.parent / "gone.git"))
    assert team.run() == cw.EXIT_ERROR
    assert sleeps == [2, 4, 8, 16] and "git fetch origin failed" in team.log() and team.prompts() == []


@posix
def test_a_push_that_failed_on_the_network_is_retried_without_running_codex_again(team, monkeypatch):
    sleeps = []
    monkeypatch.setattr(cw, "_sleep", sleeps.append)
    git(team.repo, "config", "remote.origin.pushurl", str(team.repo.parent / "gone.git"))   # fetch works, push does not
    assert team.run() == 0
    rec = team.record()
    assert rec["result"] == "push_failed" and rec["pending_result"] == "ok" and rec["pushed_utc"] == ""
    assert sleeps == [2, 4, 8, 16] and team.sha("refs/heads/codex/x1") == ""
    local = git(team.repo, "rev-parse", "codex/x1")
    assert rec["head_sha"] == local
    git(team.repo, "config", "--unset", "remote.origin.pushurl")
    assert team.run() == 0
    assert len(team.prompts()) == 1   # Codex did not run again: only the push
    rec = team.record()
    assert rec["result"] == "ok" and rec["pushed_utc"] and team.sha("refs/heads/codex/x1") == local


@posix
def test_a_rejected_push_is_recorded_and_not_retried_or_repeated(team, monkeypatch):
    sleeps = []
    monkeypatch.setattr(cw, "_sleep", sleeps.append)
    git(team.boss, "commit", "-q", "--allow-empty", "-m", "elsewhere")
    git(team.boss, "push", "-q", "origin", "main:refs/heads/codex/x1")   # somebody already put other work on that branch name
    assert team.run() == 0
    assert team.record()["result"] == "push_rejected" and sleeps == []
    assert team.run() == 0 and len(team.prompts()) == 1


def test_verification_plan_and_runner(tmp_path, monkeypatch):
    monkeypatch.delenv("SPIKE_TEAM_VERIFY", raising=False)
    plan = cw.verify_plan(tmp_path, web_changed=False)
    assert [p[0] for p in plan] == [".venv/bin/ruff check .", ".venv/bin/python -m pytest -q"]
    assert [p[1][1:] for p in plan] == [["check", "."], ["-m", "pytest", "-q"]] and {p[2] for p in plan} == {"."}
    assert len(cw.verify_plan(tmp_path, web_changed=True)) == 2   # no web/node_modules: the web checks are left out
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    assert cw.verify_plan(tmp_path, web_changed=False) == plan
    web = cw.verify_plan(tmp_path, web_changed=True)[2:]
    assert [(p[0], p[1], p[2]) for p in web] == [("npx vitest run", ["npx", "vitest", "run"], "web"),
                                                 ("npm run build", ["npm", "run", "build"], "web")]
    monkeypatch.setenv("SPIKE_TEAM_VERIFY", "make check -j2")
    assert cw.verify_plan(tmp_path, web_changed=True) == [("make check -j2", ["make", "check", "-j2"], ".")]
    code, out = cw.run_capture([sys.executable, "-c", "import sys; print('out', flush=True); print('err', file=sys.stderr); sys.exit(4)"], tmp_path, 30)
    assert code == 4 and out.split() == ["out", "err"]
    assert cw.run_capture([str(tmp_path / "no-such-tool")], tmp_path, 30)[0] == 127
    code, out = cw.run_capture([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.5)
    assert code == 124 and "timeout" in out


@posix
def test_web_checks_are_chosen_by_what_changed_under_web(team):
    w = cw.Worker(team.repo, team.state, str(team.codex))
    assert w.web_changed() is False
    (team.repo / "spike").mkdir()
    (team.repo / "spike" / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert w.web_changed() is False
    (team.repo / "web" / "src").mkdir(parents=True)
    (team.repo / "web" / "src" / "App.tsx").write_text("export {}\n", encoding="utf-8")
    assert w.web_changed() is True   # a new file counts


@posix
def test_the_real_verification_commands_run_and_a_missing_tool_fails_the_verification(team, monkeypatch):
    monkeypatch.delenv("SPIKE_TEAM_VERIFY")   # this repo has no .venv: ruff and pytest cannot be run
    assert team.run() == 0
    rec = team.record()
    assert rec["result"] == "verify_failed" and rec["pushed_utc"]
    assert [(v["cmd"], v["exit"]) for v in rec["verify"]] == [(".venv/bin/ruff check .", 127), (".venv/bin/python -m pytest -q", 127)]
    report = team.show("codex/x1", "docs/team/reports/X1.md")
    assert "### `.venv/bin/ruff check .`" in report and "- Código de salida: 127" in report and "cannot run" in report
    assert "ALGO FALLÓ" in report


@posix
def test_the_worker_only_ever_pushes_codex_branches(team):
    w = cw.Worker(team.repo, team.state, str(team.codex))
    before = team.sha("refs/heads/main")
    with pytest.raises(cw.GitError, match="only pushes codex/"):
        w.push_and_record(task("X1"), "main", "", "ok", [])
    assert team.sha("refs/heads/main") == before


@posix
def test_the_scripts_run_from_the_command_line(team):
    base = [sys.executable, str(WORKER_PY)]
    r = subprocess.run([*base, "stop", "--state", str(team.state)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and (team.state / "STOP").is_file()
    r = subprocess.run([*base, "status", "--state", str(team.state)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and json.loads(r.stdout)["stop_requested"] is True
    r = subprocess.run([*base, "run", "--repo", str(team.repo), "--state", str(team.state), "--codex", str(team.codex), "--once",
                        "--min-free-gb", "0"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert team.sha("refs/heads/codex/x1") and "pushed codex/x1" in r.stderr   # the worker log goes to stderr too
    r = subprocess.run([*base, "run", "--repo", str(team.repo), "--state", str(team.state), "--once", "--codex", "nope"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "Codex CLI" in r.stderr


@posix
def test_terminating_the_worker_stops_codex_and_releases_the_lock(team, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "sleep")
    proc = subprocess.Popen([sys.executable, str(WORKER_PY), "run", "--repo", str(team.repo), "--state", str(team.state),
                             "--codex", str(team.codex), "--min-free-gb", "0"], stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):   # Codex is up when it has written its pid
            if (team.calls / "pid-1").is_file() and (team.calls / "pid-1").read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        codex_pid = int((team.calls / "pid-1").read_text(encoding="utf-8"))
        assert cw.pid_alive(codex_pid) and (team.state / "worker.lock").is_file()
        proc.terminate()
        assert proc.wait(30) == 143
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    for _ in range(50):
        if not cw.pid_alive(codex_pid):
            break
        time.sleep(0.1)
    assert not cw.pid_alive(codex_pid) and not (team.state / "worker.lock").exists()
    assert team.sha("refs/heads/codex/x1") == ""   # nothing was pushed from the interrupted run


# ---- setup -------------------------------------------------------------------------------------------------------

FAKE_PY = r'''#!@PY@
import os, shutil, sys
from pathlib import Path
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["-m", "venv"]:
    target = Path(sys.argv[3]) / "bin" / "python"
    target.parent.mkdir(parents=True)
    shutil.copy(__file__, target)
    target.chmod(0o755)
'''


def fake_tools(tmp_path: Path) -> Path:
    """A directory with a fake python (logs its arguments, makes a venv whose python is the same script) and a fake npm."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fake-python").write_text(FAKE_PY.replace("@PY@", sys.executable), encoding="utf-8")
    (bindir / "npm").write_text('#!/bin/sh\necho "npm $* in $(basename "$PWD")" >> "$FAKE_LOG"\nmkdir -p node_modules\n',
                                encoding="utf-8")
    for name in ("fake-python", "npm"):
        (bindir / name).chmod(0o755)
    return bindir


@posix
def test_setup_creates_the_venv_and_installs_once(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "package.json").write_text("{}", encoding="utf-8")
    bindir = fake_tools(tmp_path)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.txt"))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    assert cw.main(["setup", "--repo", str(repo), "--python", str(bindir / "fake-python")]) == 0
    log = (tmp_path / "log.txt").read_text(encoding="utf-8").splitlines()
    assert log == [f"-m venv {repo / '.venv'}", "-m pip install -e .[dev]", "npm ci in web"]
    assert (repo / ".venv" / "bin" / "python").is_file() and (repo / "web" / "node_modules").is_dir()
    assert "listo" in capsys.readouterr().out
    assert cw.main(["setup", "--repo", str(repo), "--python", str(bindir / "fake-python")]) == 0   # all there: nothing runs
    assert (tmp_path / "log.txt").read_text(encoding="utf-8").splitlines() == log
    out = capsys.readouterr().out
    assert ".venv ya existe" in out and "web/node_modules ya existe" in out and "nada que hacer" in out


@posix
def test_setup_picks_the_newest_python_and_skips_npm_when_there_is_none(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "package.json").write_text("{}", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    with pytest.raises(ValueError, match="python3.13"):
        cw.setup_steps(repo, None)
    for name in ("python3.11", "python3.12"):
        (bindir / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (bindir / name).chmod(0o755)
    steps, notes = cw.setup_steps(repo, None)
    assert [s[1][0] for s in steps] == [str(bindir / "python3.12"), str(repo / ".venv" / "bin" / "python")]
    assert steps[1][1][1:] == ["-m", "pip", "install", "-e", ".[dev]"] and steps[0][1][1:3] == ["-m", "venv"]
    assert any("falta npm" in n for n in notes)


@posix
def test_setup_without_a_python_or_with_a_failing_step(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert cw.main(["setup", "--repo", str(repo)]) == 2
    assert "python3.13" in capsys.readouterr().err
    failing = tmp_path / "failing-python"
    failing.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    failing.chmod(0o755)
    assert cw.main(["setup", "--repo", str(repo), "--python", str(failing)]) == 1
    assert "código 7" in capsys.readouterr().err and not (repo / ".venv").exists()
    assert cw.main(["setup", "--repo", str(tmp_path / "nowhere")]) == 2
