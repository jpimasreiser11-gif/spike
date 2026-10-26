"""Parallel Prototypes: one build task, two approaches, built side by side and compared by what they do.

The user asks for two approaches; Forge drafts two blueprints (`approach_hint`), the user reviews both and approves.
Each approach is then built on its own git branch (`spike/proto-<id>-a`, `-b`) in its own checkout of the project's
folder, so the user's branch and files are never touched while it builds: the checkouts are `git worktree`s kept in
SPIKE's home, not in the folder. A folder that is not a repository is made one first (`git init`, then a snapshot
commit of what is there); a folder inside some other repository is refused. Each branch gets the same shared test
files, then the same tests and checks run on both:

  * `unittest`: Python's own test discovery over the checkout; the count of tests that passed;
  * `python`: a Python snippet that must run without an error (an assertion on the result, say);
  * `contains` and `words_max`: a saved file has these words / at most that many words (spike/forge/evaluate.py);
  * the deliverable checks Forge already runs (the files each step had to save exist and parse).

Code that runs does so through the `python` tool, with the user's permission and the computer's sandbox, as when
Forge imports a file it saved. The comparison table is built from those results, from `git diff` and from the clock;
no model's opinion enters it (the checker's verdict on the blueprint's criteria is kept apart, for reading). SPIKE
suggests an approach only when one has strictly more tests passed, or equal tests and strictly more checks.

Nothing is merged until the user approves one approach: then `git merge --no-ff` of that branch into the branch the
folder was on, which must still be checked out and have no uncommitted changes to tracked files; a conflict aborts the
merge and leaves the branch as it was. The other approach's branch stays (a name `git branch -D` can remove), or both
can be discarded. Only branches that SPIKE created (`spike/proto-*`) are ever deleted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spike.agent.loop import Event, call_tool
from spike.core.types import ToolCall
from spike.forge.blueprint import Blueprint, clean_path
from spike.forge.evaluate import check_name, run_check
from spike.orchestrator.orchestrator import Orchestrator, OrchestratorOptions, _merge
from spike.tools.base import PermissionBroker, ToolRegistry
from spike.tools.sandbox import strip_note

LABELS = ("a", "b")
RUN_ID = re.compile(r"[0-9a-f]{8}")
BRANCH = re.compile(r"spike/proto-[0-9a-f]{8}-[ab]")
GIT_TIMEOUT_S = 120
MAX_SNAPSHOT_FILES = 5000  # a folder bigger than this is not committed as a first snapshot
MAX_SNAPSHOT_BYTES = 200 * 1024 * 1024
MAX_TEST_FILES = 5
MAX_TEST_BYTES = 100_000  # of each shared test file
MAX_CHECKS = 12
MAX_CODE = 20_000  # of a `python` check
CHECK_KINDS = ("unittest", "python", "contains", "words_max")
IDENTITY = ("-c", "user.name=SPIKE", "-c", "user.email=spike@localhost")
EXCLUDE = (":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc")  # never part of a prototype's commit
APPROACH_HINTS = {
    "a": "Approach A: the simplest plan that meets every requirement: the fewest steps and files, nothing extra.",
    "b": ("Approach B: a different plan from A that still meets every requirement: structure the work in another "
          "way (another decomposition of the steps, another design for the files), favouring robustness."),
}
# what the python tool runs: a temporary copy of the checkout (the run writes only in its own folder), then the check
COPY_CODE = """\
import os, shutil, sys
for folder, dirs, files in os.walk({root!r}):
    dirs[:] = [d for d in dirs if d != ".git"]
    for name in files:
        if name == ".git":
            continue
        src = os.path.join(folder, name)
        dst = os.path.relpath(src, {root!r})
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copyfile(src, dst)
sys.path.insert(0, os.getcwd())
sys.dont_write_bytecode = True
"""
UNITTEST_CODE = """\
import io, json, unittest
buffer = io.StringIO()
suite = unittest.TestLoader().discover({start!r}, pattern={pattern!r})
result = unittest.TextTestRunner(stream=buffer, verbosity=0).run(suite)
bad = [str(t) for t, _ in result.failures + result.errors]
print(json.dumps({{"spike_tests": {{"run": result.testsRun, "failed": len(result.failures), "errors": len(result.errors),
                                  "skipped": len(result.skipped), "bad": bad[:20]}}}}))
print(buffer.getvalue()[-2500:])
"""


class PrototypeError(Exception):
    """Something that stops Parallel Prototypes, in words the user can act on. `status` is the HTTP status the app
    answers with: 400 a request that cannot work, 404 no such run, 409 the folder or the run is not in a state that
    allows it, 403 a merge the user has not approved."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------------------------------------ git
def git_binary() -> str | None:
    return shutil.which("git")


def git(cwd: Path, *args: str, check: bool = True, config: tuple[str, ...] = IDENTITY, hooks: Path | None = None
        ) -> subprocess.CompletedProcess[str]:
    """One git command in `cwd`, the user's git configuration left as it is (identity and hooks only for this call).
    PrototypeError with git's own message when it fails and `check` is set."""
    binary = git_binary()
    if binary is None:
        raise PrototypeError("git is not installed: Parallel Prototypes needs it (https://git-scm.com/downloads)")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in ("GIT_SSL_CAINFO",)}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"})
    hook_args = ("-c", f"core.hooksPath={hooks}") if hooks else ()
    try:
        done = subprocess.run([binary, *config, *hook_args, "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise PrototypeError(f"git {args[0]} took more than {GIT_TIMEOUT_S} s") from exc
    if check and done.returncode != 0:
        raise PrototypeError(f"git {args[0]} failed: {(done.stderr or done.stdout).strip()[:500]}")
    return done


def out(cwd: Path, *args: str, **kw: Any) -> str:
    return git(cwd, *args, **kw).stdout.strip()


def user_identity(cwd: Path) -> tuple[str, ...]:
    """SPIKE's identity for a commit only when the user has none configured (a merge is theirs)."""
    set_up = all(git(cwd, "config", key, check=False, config=()).stdout.strip() for key in ("user.name", "user.email"))
    return () if set_up else IDENTITY


def folder_size(root: Path) -> tuple[int, int]:
    files = size = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            files += 1
            with contextlib.suppress(OSError):
                size += (Path(folder) / name).stat().st_size
    return files, size


# ------------------------------------------------------------------------------------------------ tests and checks
def clean_tests(raw: Any) -> dict[str, Any]:
    """The shared tests of a run, validated: `files` (path -> text written to both branches before anything is built)
    and `checks` (what runs on both afterwards). ValueError says what is wrong."""
    if raw is None:
        return {"files": {}, "checks": []}
    if not isinstance(raw, dict) or set(raw) - {"files", "checks"}:
        raise ValueError("tests takes 'files' and 'checks'")
    files = {} if raw.get("files") is None else raw["files"]
    checks = [] if raw.get("checks") is None else raw["checks"]
    if not isinstance(files, dict) or not isinstance(checks, list):
        raise ValueError("'files' must be an object and 'checks' a list")
    if len(files) > MAX_TEST_FILES or len(checks) > MAX_CHECKS:
        raise ValueError(f"at most {MAX_TEST_FILES} test files and {MAX_CHECKS} checks")
    cleaned_files: dict[str, str] = {}
    for path, content in files.items():
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TEST_BYTES:
            raise ValueError(f"test file '{path}' must be text of at most {MAX_TEST_BYTES // 1000} KB")
        cleaned_files[clean_path(path)] = content
    cleaned: list[dict[str, Any]] = []
    for i, check in enumerate(checks, 1):
        if not isinstance(check, dict) or check.get("kind") not in CHECK_KINDS:
            raise ValueError(f"check {i}: 'kind' must be one of {', '.join(CHECK_KINDS)}")
        kind = check["kind"]
        item: dict[str, Any] = {"kind": kind, "name": str(check.get("name") or "")[:120]}
        if kind == "python":
            code = check.get("code")
            if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE:
                raise ValueError(f"check {i}: 'code' must be Python text of at most {MAX_CODE} characters")
            item["code"] = code
        elif kind == "unittest":
            start = check.get("start") or "."
            item["start"] = "." if start == "." else clean_path(start)
            pattern = str(check.get("pattern") or "test*.py")
            if not re.fullmatch(r"[\w*?.\-]{1,60}", pattern):
                raise ValueError(f"check {i}: 'pattern' is a file name pattern such as test*.py")
            item["pattern"] = pattern
        else:
            item["path"] = clean_path(check.get("path") or "")
            if kind == "contains":
                words = [str(w)[:200] for w in (check.get("all") or []) if str(w).strip()]
                if not words:
                    raise ValueError(f"check {i}: 'all' must list the words the file has")
                item["all"] = words[:20]
            else:
                limit = check.get("max")
                if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                    raise ValueError(f"check {i}: 'max' must be a whole number of words")
                item["max"] = limit
        cleaned.append(item)
    return {"files": cleaned_files, "checks": cleaned}


def default_tests(tests: dict[str, Any]) -> dict[str, Any]:
    """Test files and no `unittest` check: the tests run, found from the folder of the first test file."""
    if tests["files"] and not any(c["kind"] == "unittest" for c in tests["checks"]):
        folder = Path(next(iter(tests["files"]))).parent.as_posix()
        return {**tests, "checks": [{"kind": "unittest", "name": "", "start": folder, "pattern": "test*.py"},
                                    *tests["checks"]]}
    return tests


def tests_prompt(tests: dict[str, Any]) -> str:
    """What the builders are told about the tests: the text of the shared files, so the result can satisfy them."""
    if not tests["files"]:
        return ""
    body = "\n\n".join(f"## {path}\n```\n{content[:6000]}\n```" for path, content in tests["files"].items())
    return ("\n\n# Acceptance tests (already in the folder; they run on your result, do not change them)\n" + body)


def parse_unittest(content: str) -> dict[str, Any]:
    """The counts the unittest script printed, or {} when it did not get that far (an import error, a timeout)."""
    for line in strip_note(content).splitlines():
        if line.startswith('{"spike_tests"'):
            try:
                return dict(json.loads(line)["spike_tests"])
            except (ValueError, KeyError, TypeError):
                return {}
    return {}


async def run_checks(root: Path, tests: dict[str, Any], tools: ToolRegistry, broker: PermissionBroker,
                     deliverables: list[dict[str, Any]], tag: dict[str, Any], outcome: list[Any]) -> AsyncIterator[Event]:
    """Run the tests and checks on one checkout. Code goes through the `python` tool and the broker (the user's
    permission); the rest reads files. Leaves `{"tests": ..., "checks": ...}` in `outcome`."""
    python = tools.get("python")
    tests_result: dict[str, Any] = {"ran": False, "reason": "no tests", "passed": 0, "total": 0, "failed": []}
    items: list[dict[str, Any]] = []
    for d in deliverables:  # saved, and SPIKE's own format check of it (Forge's) did not fail
        program = d.get("program") or {}
        failed = d["ok"] and program.get("ok") is False
        items.append({"name": d["path"], "kind": "deliverable", "ok": bool(d["ok"]) and not failed,
                      "note": "not saved" if not d["ok"] else str(program.get("note", ""))[:300] if failed else ""})
    for n, check in enumerate(tests["checks"], 1):
        kind, name = check["kind"], check.get("name") or ""
        if kind in ("contains", "words_max"):
            ok, why = run_check(check, root)
            items.append({"name": name or check_name(check), "kind": kind, "ok": ok, "note": why})
            continue
        content, ok, note = "", False, "the python tool is not available"
        if python is not None:
            code = COPY_CODE.format(root=str(root)) + (
                UNITTEST_CODE.format(start=check["start"], pattern=check["pattern"]) if kind == "unittest"
                else check["code"])
            box: list[Any] = []
            call = ToolCall(id=f"proto-{tag.get('proto', '')}-{n}", name="python", arguments={"code": code})
            async for ev in call_tool(python, call, broker, None, tag, box):
                yield ev
            content, ok = box[0], box[1]
            lines = strip_note(content).strip().splitlines()
            note = "" if ok else (lines[-1][:300] if lines else "no output")
        if kind != "unittest":
            items.append({"name": name or f"python check {n}", "kind": kind, "ok": ok, "note": note})
            continue
        counts = parse_unittest(content)
        if not counts:  # it never printed its counts: the suite could not be loaded, or the run was refused
            if not tests_result["ran"]:
                tests_result = {**tests_result, "reason": note or "the tests did not run"}
            continue
        bad = int(counts["failed"]) + int(counts["errors"])
        tests_result = {"ran": True, "reason": "", "total": tests_result["total"] + int(counts["run"]),
                        "passed": tests_result["passed"] + max(0, int(counts["run"]) - bad),
                        "failed": tests_result["failed"] + list(counts.get("bad") or [])}
    outcome[:] = [{"tests": tests_result, "checks": {"passed": sum(1 for i in items if i["ok"]), "total": len(items),
                                                      "items": items}}]


def compare(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The comparison table and, when the numbers tell them apart, the approach they favour. Only the results of the
    runs go in: tests passed, checks passed, files and lines changed, time."""
    rows = []
    for label, r in results.items():
        rows.append({"label": label, "built": r["status"] == "built", "tests_passed": r["tests"]["passed"],
                     "tests_total": r["tests"]["total"], "tests_ran": r["tests"]["ran"],
                     "checks_passed": r["checks"]["passed"], "checks_total": r["checks"]["total"],
                     "files_changed": r["files"]["count"], "insertions": r["files"]["insertions"],
                     "deletions": r["files"]["deletions"], "seconds": r["seconds"]["total"]})
    leader, basis = None, None
    if len(rows) == 2:
        a, b = rows
        for key in ("tests_passed", "checks_passed"):
            if a[key] != b[key]:
                leader, basis = (a if a[key] > b[key] else b)["label"], key.split("_")[0]
                break
    return {"rows": rows, "leader": leader, "basis": basis}


# ------------------------------------------------------------------------------------------------ the run
@dataclass
class Approach:
    label: str
    blueprint: Blueprint
    branch: str
    path: Path
    start: str = ""  # the commit with the shared tests: what "files changed" counts from
    result: dict[str, Any] = field(default_factory=dict)
    blueprint_data: dict[str, Any] | None = None  # the blueprint as saved, for a run loaded from disk


@dataclass
class PrototypeRun:
    id: str
    root: Path
    home: Path  # SPIKE's folder for this run: the checkouts and run.json
    task: str
    base_branch: str
    base_commit: str
    tests: dict[str, Any]
    approaches: list[Approach]
    dirty: int = 0  # tracked or untracked paths with changes the prototypes do not include
    status: str = "building"  # building | built | merged | discarded
    comparison: dict[str, Any] = field(default_factory=dict)
    merged: dict[str, Any] | None = None

    @property
    def record_path(self) -> Path:
        return self.home / "run.json"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "task": self.task, "status": self.status,
                "base": {"branch": self.base_branch, "commit": self.base_commit}, "dirty": self.dirty,
                "tests": {"files": sorted(self.tests["files"]), "checks": self.tests["checks"]},
                "approaches": [{"label": a.label, "branch": a.branch, "goal": a.blueprint.goal, "start": a.start,
                                "blueprint": a.blueprint_data or a.blueprint.to_dict(), **a.result}
                               for a in self.approaches],
                "comparison": self.comparison, "merged": self.merged}

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.record_path.write_text(json.dumps({**self.public(), "root": str(self.root)}, indent=2, ensure_ascii=False),
                                    encoding="utf-8")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def start(root: Path, prototypes_home: Path, task: str, blueprints: list[Blueprint], tests: dict[str, Any]
          ) -> PrototypeRun:
    """Prepare a run: make `root` a repository if it is not one, then a branch and a checkout for each blueprint with
    the shared test files committed on it. The user's branch and working files are not changed (a repository made here
    gets a first commit with the folder's files). PrototypeError when it cannot be done."""
    root = root.resolve()
    if len(blueprints) != 2:
        raise PrototypeError("Parallel Prototypes builds two approaches")
    if git_binary() is None:
        raise PrototypeError("git is not installed: Parallel Prototypes needs it (https://git-scm.com/downloads)")
    root.mkdir(parents=True, exist_ok=True)
    top = git(root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode == 0:
        if Path(top.stdout.strip()).resolve() != root:
            raise PrototypeError(f"{root} is inside the git repository {top.stdout.strip()}: Parallel Prototypes "
                                 "needs a folder that is a repository of its own")
    else:
        files, size = folder_size(root)
        if files > MAX_SNAPSHOT_FILES or size > MAX_SNAPSHOT_BYTES:
            raise PrototypeError(f"the folder has {files} files ({size // 1024**2} MB): too much to start a git "
                                 "repository in. Use a project with fewer files")
        git(root, "init")
    if git(root, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:  # nothing committed yet
        files, size = folder_size(root)
        if files > MAX_SNAPSHOT_FILES or size > MAX_SNAPSHOT_BYTES:
            raise PrototypeError("the repository has no commit and its folder is too big to snapshot")
        git(root, "add", "-A", "--", ".", *EXCLUDE)
        git(root, "commit", "--allow-empty", "-m", "SPIKE: snapshot of the folder before the prototypes")
    head = git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if head.returncode != 0 or not head.stdout.strip():
        raise PrototypeError("the folder's repository is not on a branch (detached HEAD): check out a branch first")
    base_branch, base_commit = head.stdout.strip(), out(root, "rev-parse", "HEAD")
    dirty = len([line for line in out(root, "status", "--porcelain").splitlines() if line.strip()])
    run_id = new_id()
    home = prototypes_home / run_id
    hooks = home / "no-hooks"
    hooks.mkdir(parents=True)
    approaches = []
    try:
        for label, blueprint in zip(LABELS, blueprints, strict=True):
            approach = Approach(label, blueprint, f"spike/proto-{run_id}-{label}", home / label)
            git(root, "worktree", "add", "-b", approach.branch, str(approach.path), base_commit, hooks=hooks)
            approaches.append(approach)
            for rel, content in tests["files"].items():
                target = approach.path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            if tests["files"]:
                git(approach.path, "add", "-A", "--", ".", *EXCLUDE, hooks=hooks)
                git(approach.path, "commit", "-m", "SPIKE: shared acceptance tests", hooks=hooks)
            approach.start = out(approach.path, "rev-parse", "HEAD")
    except PrototypeError:
        remove(root, approaches, home, hooks)
        shutil.rmtree(home, ignore_errors=True)
        raise
    run = PrototypeRun(run_id, root, home, task, base_branch, base_commit, tests, approaches, dirty)
    run.save()
    return run


def remove(root: Path, approaches: list[Approach], home: Path, hooks: Path | None = None, branches: bool = True) -> None:
    """Take the checkouts away and, with `branches`, the branches SPIKE made (nothing else is ever deleted)."""
    for a in approaches:
        if a.path.exists():
            git(root, "worktree", "remove", "--force", str(a.path), check=False, hooks=hooks)
            shutil.rmtree(a.path, ignore_errors=True)
    git(root, "worktree", "prune", check=False)
    if branches:
        for a in approaches:
            if BRANCH.fullmatch(a.branch):
                git(root, "branch", "-D", a.branch, check=False)
    shutil.rmtree(home / "no-hooks", ignore_errors=True)


def diff_stat(approach: Approach) -> dict[str, Any]:
    """Files changed from the shared-tests commit to the branch's tip, with the lines added and removed."""
    paths, ins, dele = [], 0, 0
    for line in out(approach.path, "diff", "--numstat", approach.start, "HEAD").splitlines():
        added, removed, path = line.split("\t", 2)
        paths.append(path)
        ins += int(added) if added.isdigit() else 0
        dele += int(removed) if removed.isdigit() else 0
    return {"count": len(paths), "paths": paths[:50], "insertions": ins, "deletions": dele}


def commit_build(approach: Approach, hooks: Path) -> str:
    """Commit what the build saved in the checkout; the tip's hash (the start commit when nothing was saved)."""
    git(approach.path, "add", "-A", "--", ".", *EXCLUDE, hooks=hooks)
    if out(approach.path, "status", "--porcelain", "--untracked-files=no"):
        git(approach.path, "commit", "-m", f"SPIKE prototype {approach.label.upper()}: {approach.blueprint.goal[:80]}",
            hooks=hooks)
    return out(approach.path, "rev-parse", "HEAD")


async def build(run: PrototypeRun, approach: Approach, orchestrator: Orchestrator, options: OrchestratorOptions,
                tools: ToolRegistry, broker: PermissionBroker) -> AsyncIterator[Event]:
    """Build one approach in its checkout, commit it and run the shared tests and checks on it. Its events carry
    `proto: <label>`; the last is `proto_result` with the numbers. A build that raises is a result with an error."""
    tag = {"proto": approach.label}
    hooks = run.home / "no-hooks"
    started = time.perf_counter()
    yield {"type": "proto_build", **tag, "branch": approach.branch, "goal": approach.blueprint.goal}
    error: str | None = None
    deliverables: list[dict[str, Any]] = []
    try:
        async for ev in orchestrator.run([], run.task + tests_prompt(run.tests), options):
            if ev["type"] == "forge_report":
                deliverables = list(ev.get("deliverables") or [])
            elif ev["type"] == "done":
                error = ev.get("error")
            yield {**ev, **tag}
    except Exception as exc:  # a crash is a result, not a failed run
        error = f"{exc.__class__.__name__}: {exc}"
        yield {"type": "error", "message": error, **tag}
    built = time.perf_counter()
    try:
        tip = await asyncio.to_thread(commit_build, approach, hooks)
        files = await asyncio.to_thread(diff_stat, approach)
    except PrototypeError as exc:
        tip, files, error = approach.start, {"count": 0, "paths": [], "insertions": 0, "deletions": 0}, str(exc)
    yield {"type": "proto_checks", **tag}
    box: list[Any] = []
    async for ev in run_checks(approach.path, run.tests, tools, broker, deliverables, tag, box):
        yield ev
    checked = time.perf_counter()
    result = box[0] if box else {"tests": {"ran": False, "reason": "no result", "passed": 0, "total": 0, "failed": []},
                                 "checks": {"passed": 0, "total": 0, "items": []}}
    approach.result = {"status": "failed" if error and not files["count"] else "built", "error": error,
                       "commit": tip, **result, "files": files,
                       "seconds": {"build": round(built - started, 2), "tests": round(checked - built, 2),
                                   "total": round(checked - started, 2)}}
    yield {"type": "proto_result", **tag, **approach.result}


async def run_all(run: PrototypeRun, orchestrator_for: Callable[[Approach], tuple[Orchestrator, OrchestratorOptions,
                                                                                  ToolRegistry]],
                  broker: PermissionBroker, concurrent: bool = False) -> AsyncIterator[Event]:
    """Build both approaches (one after the other, or together when `concurrent`), then compare them. The stream
    ends with `proto_compare`; the run is saved with its numbers and waits, `built`, for the user's pick."""
    yield {"type": "proto_start", **run.public()}
    runs = []
    for approach in run.approaches:
        orchestrator, options, tools = orchestrator_for(approach)
        runs.append(build(run, approach, orchestrator, options, tools, broker))
    if concurrent:
        async for ev in _merge(runs):
            yield ev
    else:
        for item in runs:
            async for ev in item:
                yield ev
    run.comparison = compare({a.label: a.result for a in run.approaches})
    run.status = "built"
    run.save()
    yield {"type": "proto_compare", "id": run.id, **run.comparison}


# ------------------------------------------------------------------------------------------------ the user's pick
def load(prototypes_home: Path, run_id: str) -> PrototypeRun:
    """A saved run. PrototypeError when there is none."""
    if not RUN_ID.fullmatch(run_id):
        raise PrototypeError("no such prototype run", 404)
    path = prototypes_home / run_id / "run.json"
    if not path.is_file():
        raise PrototypeError("no such prototype run", 404)
    data = json.loads(path.read_text(encoding="utf-8"))
    home = prototypes_home / run_id
    approaches = []
    for a in data["approaches"]:
        blueprint = Blueprint(goal=a["blueprint"]["goal"], requirements=a["blueprint"]["requirements"], steps=[],
                              criteria=a["blueprint"]["criteria"], method=a["blueprint"]["method"],
                              note=a["blueprint"]["note"])
        extras = {k: v for k, v in a.items() if k not in ("label", "branch", "goal", "blueprint", "start")}
        approaches.append(Approach(a["label"], blueprint, a["branch"], home / a["label"], a.get("start", ""), extras,
                                   a["blueprint"]))
    return PrototypeRun(data["id"], Path(data["root"]), home, data["task"], data["base"]["branch"],
                        data["base"]["commit"], {"files": {p: "" for p in data["tests"]["files"]},
                                                 "checks": data["tests"]["checks"]}, approaches, data["dirty"],
                        data["status"], data["comparison"], data.get("merged"))


def list_runs(prototypes_home: Path, root: Path | None = None) -> list[dict[str, Any]]:
    """The saved runs (of the folder `root`, when given), newest first, as their records; a run still `built` is
    waiting for the user's pick."""
    found = []
    for path in prototypes_home.glob("*/run.json") if prototypes_home.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not RUN_ID.fullmatch(str(data.get("id"))):
            continue
        if root is None or str(data.get("root")) == str(root.resolve()):
            found.append((path.stat().st_mtime, {k: v for k, v in data.items() if k != "root"}))
    return [record for _, record in sorted(found, key=lambda item: item[0], reverse=True)]


def forget(prototypes_home: Path, root: Path) -> None:
    """Delete the checkouts and records of a folder's runs: its project was deleted, and its repository with it."""
    for record in list_runs(prototypes_home, root):
        shutil.rmtree(prototypes_home / record["id"], ignore_errors=True)


def check_merge(run: PrototypeRun) -> None:
    """The folder is as the merge needs it: still on the branch the run started from, nothing uncommitted in tracked
    files. PrototypeError (409 in the app) says what to do otherwise."""
    head = git(run.root, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    if head != run.base_branch:
        raise PrototypeError(f"the folder is on '{head or 'no branch'}', not on '{run.base_branch}' where the "
                             f"prototypes started: check out '{run.base_branch}' to merge", 409)
    if out(run.root, "status", "--porcelain", "--untracked-files=no"):
        raise PrototypeError("the folder has uncommitted changes to tracked files: commit or stash them first, "
                             "then merge", 409)


def merge(run: PrototypeRun, choice: str, approved: bool) -> dict[str, Any]:
    """Merge the chosen approach's branch into the original branch, if the user approved. PrototypeError: not
    approved, not merge-able now, or a conflict (the merge is aborted and nothing changes)."""
    if not approved:
        raise PrototypeError("merging needs the user's approval", 403)
    if run.status != "built":
        raise PrototypeError(f"this run is {run.status}: only a run that was built can be merged", 409)
    chosen = next((a for a in run.approaches if a.label == choice), None)
    if chosen is None:
        raise PrototypeError("choose approach 'a' or 'b'")
    if not BRANCH.fullmatch(chosen.branch) or git(run.root, "rev-parse", "--verify", chosen.branch,
                                                  check=False).returncode != 0:
        raise PrototypeError(f"the branch {chosen.branch} no longer exists", 409)
    check_merge(run)
    before = out(run.root, "rev-parse", "HEAD")
    done = git(run.root, "merge", "--no-ff", "-m", f"Merge SPIKE prototype {choice.upper()}: {chosen.blueprint.goal[:80]}",
               chosen.branch, check=False, config=user_identity(run.root))
    if done.returncode != 0:
        conflicts = out(run.root, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
        git(run.root, "merge", "--abort", check=False)
        raise PrototypeError("the merge was stopped and undone: " + (
            f"{', '.join(conflicts[:5])} changed on both sides" if conflicts
            else (done.stderr or done.stdout).strip()[:300]), 409)
    other = next(a for a in run.approaches if a is not chosen)
    remove(run.root, run.approaches, run.home, branches=False)
    git(run.root, "branch", "-d", chosen.branch, check=False)
    run.status = "merged"
    run.merged = {"choice": choice, "branch": chosen.branch, "into": run.base_branch, "from": before,
                  "commit": out(run.root, "rev-parse", "HEAD"), "kept_branch": other.branch}
    run.save()
    return run.merged


def discard(run: PrototypeRun) -> None:
    """Drop the run: the checkouts and both branches (only the ones SPIKE made)."""
    if run.status == "merged":
        raise PrototypeError("this run was merged; its other branch can be removed with git branch -D", 409)
    remove(run.root, run.approaches, run.home)
    run.status = "discarded"
    run.save()
