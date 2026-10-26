"""Parallel Prototypes: one build task, two approaches on two git branches, the same tests run on both, and nothing
merged until the user approves one. The git here is real (temporary repositories); the model is a fake executor that
saves fixed files, and the tests are Python's own unittest run through the `python` tool, so the comparison table is
built from real results."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.forge import prototypes
from spike.forge.blueprint import from_user
from spike.forge.prototypes import Approach, PrototypeError
from spike.orchestrator.orchestrator import OrchestratorOptions
from spike.projects import ProjectFiles
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker, ToolRegistry
from spike.tools.builtin import default_registry
from tests.helpers import ScriptedProvider, call, text

CATALOG = load_catalog()
SLUG_A = ('import re\nimport unicodedata\n\n\ndef slugify(text):\n'
          '    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()\n'
          '    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")\n')
SLUG_B = 'import re\n\n\ndef slugify(text):\n    return re.sub(r"\\W+", "-", text.lower()).strip("-")\n'  # keeps the ñ
TEST_SLUG = '''import unittest

from slug import slugify


class SlugTests(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(slugify("Hola Mundo"), "hola-mundo")

    def test_accents(self):
        self.assertEqual(slugify("Año Nuevo"), "ano-nuevo")

    def test_symbols(self):
        self.assertEqual(slugify("¡Hola, mundo!"), "hola-mundo")
'''
TESTS = {"files": {"tests/test_slug.py": TEST_SLUG},
         "checks": [{"kind": "python", "name": "accents", "code": "from slug import slugify\n"
                                                                   "assert slugify('Año Nuevo') == 'ano-nuevo'\n"}]}
FILES = {"a": {"slug.py": SLUG_A}, "b": {"slug.py": SLUG_B}}
ALLOWED = PermissionBroker({"python": "allow", "write_file": "allow"})


def shared_tests() -> dict:
    return prototypes.default_tests(prototypes.clean_tests(TESTS))


def blueprint(label: str):
    return from_user({"goal": f"Slug {label}", "requirements": ["slugify(text)"], "criteria": ["slugify exists"],
                      "steps": [{"id": "t1", "specialist": "code", "instruction": f"Guarda slug.py (enfoque {label})",
                                 "deliverables": ["slug.py"]}]}, CATALOG)


# ---------------------------------------------------------------- the fake executor and git helpers
class Builder:
    """What an Orchestrator is to `build`: it saves the files it was given in its checkout, as a Forge run does."""

    def __init__(self, root: Path, files: dict[str, str], crash: bool = False):
        self.root, self.files, self.crash, self.asked = root, files, crash, ""

    async def run(self, history, user_text, options):
        self.asked = user_text
        if self.crash:
            raise RuntimeError("the model went away")
        for rel, content in self.files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(content, encoding="utf-8")
        yield {"type": "delta", "text": "listo"}
        yield {"type": "forge_report", "verified": True, "note": "", "criteria": [], "rounds": 1, "unresolved": [],
               "deliverables": [{"subtask": "t1", "path": p, "ok": True, "bytes": len(c)} for p, c in self.files.items()]}
        yield {"type": "done", "text": "listo", "error": None}


def executor(files=FILES, crash=(), builders=None):
    def orchestrator_for(approach: Approach):
        builder = Builder(approach.path, files[approach.label], approach.label in crash)
        (builders if builders is not None else {})[approach.label] = builder
        return builder, OrchestratorOptions(forge=approach.blueprint), default_registry(approach.path)
    return orchestrator_for


async def play(run, concurrent=False, **kw):
    return [e async for e in prototypes.run_all(run, executor(**kw), ALLOWED, concurrent=concurrent)]


def sh(root: Path, *args: str) -> str:
    return prototypes.out(root, *args)


def make_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    prototypes.git(root, "init")
    prototypes.git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    prototypes.git(root, "add", "-A")
    prototypes.git(root, "commit", "-m", "first")
    return root


def branches(root: Path) -> dict[str, str]:
    lines = sh(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads").splitlines()
    return dict(line.split(" ") for line in lines)


def users_branches(root: Path) -> dict[str, str]:
    return {k: v for k, v in branches(root).items() if not k.startswith("refs/heads/spike/proto-")}


def checkouts(root: Path) -> int:
    return len(sh(root, "worktree", "list").splitlines())


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = make_repo(tmp_path / "project", {"README.md": "# project\n", "notes.txt": "mine\n"})
    prototypes.git(root, "branch", "feature")
    return root


@pytest.fixture
def built(repo, tmp_path):
    """A run of the two approaches, built and compared, in `repo`."""
    import asyncio

    run = prototypes.start(repo, tmp_path / "home", "Haz slugify", [blueprint("A"), blueprint("B")], shared_tests())
    events = asyncio.run(play(run))
    return run, events


# ---------------------------------------------------------------- two branches, same tests, real results
async def test_two_branches_are_built_and_compared_by_tests_that_really_ran(repo, tmp_path):
    before_branches, before_status = users_branches(repo), sh(repo, "status", "--porcelain")
    run = prototypes.start(repo, tmp_path / "home", "Haz slugify", [blueprint("A"), blueprint("B")], shared_tests())
    a, b = run.approaches
    assert (a.branch, b.branch) == (f"spike/proto-{run.id}-a", f"spike/proto-{run.id}-b")
    assert run.base_branch == "main" and run.base_commit == sh(repo, "rev-parse", "main")
    builders: dict = {}
    events = await play(run, builders=builders)

    kinds = [e["type"] for e in events]
    assert kinds[0] == "proto_start" and kinds[-1] == "proto_compare"
    assert [e["proto"] for e in events if e["type"] == "proto_build"] == ["a", "b"]
    assert [e["proto"] for e in events if e["type"] == "proto_result"] == ["a", "b"]
    assert all(e["proto"] in ("a", "b") for e in events if e["type"] not in ("proto_start", "proto_compare"))
    assert "Acceptance tests" in builders["a"].asked and "def test_accents" in builders["b"].asked  # builders see them

    # the numbers come from the unittest runs and the checks, not from any model
    assert a.result["tests"] == {"ran": True, "reason": "", "passed": 3, "total": 3, "failed": []}
    assert (b.result["tests"]["passed"], b.result["tests"]["total"]) == (2, 3)
    assert len(b.result["tests"]["failed"]) == 1 and "test_accents" in b.result["tests"]["failed"][0]
    assert [(i["name"], i["ok"]) for i in a.result["checks"]["items"]] == [("slug.py", True), ("accents", True)]
    assert [(i["name"], i["ok"]) for i in b.result["checks"]["items"]] == [("slug.py", True), ("accents", False)]
    assert "AssertionError" in b.result["checks"]["items"][1]["note"]
    assert (a.result["checks"]["passed"], b.result["checks"]["passed"]) == (2, 1)
    assert a.result["files"]["paths"] == ["slug.py"] and a.result["files"]["count"] == 1
    assert a.result["files"]["insertions"] == len(SLUG_A.splitlines()) and a.result["files"]["deletions"] == 0
    assert a.result["status"] == "built" and a.result["seconds"]["total"] >= a.result["seconds"]["build"] >= 0

    comparison = run.comparison
    assert comparison["leader"] == "a" and comparison["basis"] == "tests"
    rows = {r["label"]: r for r in comparison["rows"]}
    assert (rows["a"]["tests_passed"], rows["a"]["tests_total"], rows["b"]["tests_passed"]) == (3, 3, 2)
    assert (rows["a"]["checks_passed"], rows["a"]["checks_total"], rows["b"]["files_changed"]) == (2, 2, 1)
    assert events[-1]["rows"] == comparison["rows"] and run.status == "built"

    # two real branches from the same commit, each with the shared tests and its own build
    for approach in run.approaches:
        prototypes.git(repo, "merge-base", "--is-ancestor", run.base_commit, approach.branch)
    assert sh(repo, "show", f"{a.branch}:slug.py") == SLUG_A.strip() and sh(repo, "show", f"{b.branch}:slug.py") == SLUG_B.strip()
    assert sh(repo, "show", f"{a.start}:tests/test_slug.py") == TEST_SLUG.strip()
    assert sh(repo, "rev-list", "--count", f"{run.base_commit}..{a.branch}") == "2"  # tests, then the build
    # the user's branches and working tree are exactly as they were; nothing was merged
    assert users_branches(repo) == before_branches and sh(repo, "status", "--porcelain") == before_status == ""
    assert not (repo / "slug.py").exists() and (repo / "notes.txt").read_text(encoding="utf-8") == "mine\n"
    assert sh(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    # the run is on disk, with the numbers, for the user to come back to
    assert prototypes.load(tmp_path / "home", run.id).public() == run.public()
    assert json.loads((run.home / "run.json").read_text(encoding="utf-8"))["comparison"]["leader"] == "a"


async def test_running_both_builds_together_gives_the_same_table(repo, tmp_path):
    run = prototypes.start(repo, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    events = await play(run, concurrent=True)
    assert events[-1]["leader"] == "a" and sorted(e["proto"] for e in events if e["type"] == "proto_result") == ["a", "b"]
    assert [r["tests_passed"] for r in run.comparison["rows"]] == [3, 2]


async def test_a_build_that_crashes_is_a_result_and_the_other_one_still_counts(repo, tmp_path):
    run = prototypes.start(repo, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    events = await play(run, crash=("b",))
    b = run.approaches[1]
    assert b.result["status"] == "failed" and "RuntimeError: the model went away" in b.result["error"]
    assert b.result["files"]["count"] == 0 and b.result["tests"]["passed"] == 0
    assert any(e["type"] == "error" and e["proto"] == "b" for e in events)
    assert run.approaches[0].result["tests"]["passed"] == 3 and run.comparison["leader"] == "a"
    assert sh(repo, "rev-parse", b.branch) == b.start  # nothing was saved on it


async def test_a_dirty_folder_is_counted_and_left_alone(repo, tmp_path):
    (repo / "notes.txt").write_text("changed\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("new\n", encoding="utf-8")
    run = prototypes.start(repo, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    await play(run)
    assert run.dirty == 2
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "changed\n" and (repo / "scratch.txt").is_file()
    assert not (run.approaches[0].path / "scratch.txt").exists()  # the prototypes start from the commit, not from it


# ---------------------------------------------------------------- the user's pick: nothing merges without approval
def test_nothing_merges_without_the_users_approval(built, repo):
    run, _ = built
    head = sh(repo, "rev-parse", "HEAD")
    with pytest.raises(PrototypeError, match="approval") as err:
        prototypes.merge(run, "a", False)
    assert err.value.status == 403
    assert sh(repo, "rev-parse", "HEAD") == head and not (repo / "slug.py").exists() and run.status == "built"
    with pytest.raises(PrototypeError, match="choose approach"):
        prototypes.merge(run, "c", True)


def test_the_approved_approach_is_merged_into_the_original_branch_and_the_other_is_kept(built, repo):
    run, _ = built
    a, b = run.approaches
    merged = prototypes.merge(run, "a", True)
    assert (repo / "slug.py").read_text(encoding="utf-8") == SLUG_A and (repo / "tests" / "test_slug.py").is_file()
    assert len(sh(repo, "rev-list", "--parents", "-n1", "HEAD").split()) == 3  # a merge commit: two parents
    assert merged["commit"] == sh(repo, "rev-parse", "HEAD") and merged["into"] == "main" and merged["choice"] == "a"
    assert run.status == "merged" and merged["kept_branch"] == b.branch
    assert b.branch in sh(repo, "branch", "--list") and a.branch not in sh(repo, "branch", "--list")
    assert sh(repo, "rev-parse", "feature") == run.base_commit  # the user's other branch is where it was
    assert checkouts(repo) == 1 and sh(repo, "status", "--porcelain") == ""
    assert json.loads((run.home / "run.json").read_text(encoding="utf-8"))["merged"]["choice"] == "a"
    with pytest.raises(PrototypeError, match="merged") as err:  # a second merge, or a discard, is refused
        prototypes.merge(run, "b", True)
    assert err.value.status == 409
    with pytest.raises(PrototypeError, match="merged"):
        prototypes.discard(run)


def test_a_conflict_stops_the_merge_and_changes_nothing(built, repo):
    run, _ = built
    (repo / "slug.py").write_text("def slugify(text):\n    return 'mine'\n", encoding="utf-8")  # the user wrote it too
    prototypes.git(repo, "add", "slug.py")
    prototypes.git(repo, "commit", "-m", "my own slug")
    head = sh(repo, "rev-parse", "HEAD")
    with pytest.raises(PrototypeError, match="stopped and undone") as err:
        prototypes.merge(run, "a", True)
    assert err.value.status == 409 and "slug.py" in str(err.value)
    assert sh(repo, "rev-parse", "HEAD") == head and sh(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists() and "mine" in (repo / "slug.py").read_text(encoding="utf-8")
    assert run.status == "built" and run.approaches[0].branch in sh(repo, "branch", "--list")  # still there to retry


def test_the_folder_must_still_be_as_the_merge_needs_it(built, repo):
    run, _ = built
    (repo / "README.md").write_text("edited, not committed\n", encoding="utf-8")
    with pytest.raises(PrototypeError, match="uncommitted changes") as err:
        prototypes.merge(run, "b", True)
    assert err.value.status == 409 and (repo / "README.md").read_text(encoding="utf-8") == "edited, not committed\n"
    prototypes.git(repo, "checkout", "--", "README.md")
    prototypes.git(repo, "checkout", "feature")
    with pytest.raises(PrototypeError, match="not on 'main'") as err:
        prototypes.merge(run, "b", True)
    assert err.value.status == 409 and sh(repo, "rev-parse", "HEAD") == run.base_commit and run.status == "built"
    prototypes.git(repo, "checkout", "main")
    prototypes.git(repo, "worktree", "remove", "--force", str(run.approaches[1].path))
    prototypes.git(repo, "branch", "-D", run.approaches[1].branch)  # the user deleted it by hand
    with pytest.raises(PrototypeError, match="no longer exists"):
        prototypes.merge(run, "b", True)


def test_discarding_removes_only_the_branches_spike_made(built, repo):
    run, _ = built
    mine = users_branches(repo)
    assert checkouts(repo) == 3
    prototypes.discard(run)
    assert run.status == "discarded" and checkouts(repo) == 1
    assert "spike/proto" not in sh(repo, "branch", "--list") and users_branches(repo) == mine
    with pytest.raises(PrototypeError, match="discarded"):
        prototypes.merge(run, "a", True)


def test_a_branch_that_spike_did_not_make_is_never_deleted(repo, tmp_path):
    blueprints = blueprint("A")
    stray = Approach("a", blueprints, "main", tmp_path / "nowhere")
    prototypes.remove(repo, [stray], tmp_path / "home")
    assert "main" in sh(repo, "branch", "--list")
    assert not prototypes.BRANCH.fullmatch("feature") and not prototypes.BRANCH.fullmatch("spike/proto-abc-a")
    assert prototypes.BRANCH.fullmatch("spike/proto-0123abcd-b")


# ---------------------------------------------------------------- the folder: git made when absent, refused when nested
def test_a_folder_that_is_not_a_repository_is_made_one_without_touching_its_files(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    plain = tmp_path / "plain"
    (plain / "__pycache__").mkdir(parents=True)
    (plain / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (plain / "__pycache__" / "x.pyc").write_bytes(b"\0")
    run = prototypes.start(plain, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert (plain / ".git").exists() and run.base_branch
    assert sh(plain, "ls-tree", "-r", "--name-only", "HEAD").splitlines() == ["data.csv"]  # the snapshot, no bytecode
    assert (plain / "data.csv").read_text(encoding="utf-8") == "a,b\n1,2\n" and (plain / "__pycache__" / "x.pyc").is_file()
    assert sh(plain, "status", "--porcelain") == "?? __pycache__/"  # still the user's, still untracked
    prototypes.discard(run)
    assert "spike/proto" not in sh(plain, "branch", "--list")


def test_an_empty_folder_gets_a_repository_and_an_empty_first_commit(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    run = prototypes.start(tmp_path / "new" / "deep", tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert sh(run.root, "rev-list", "--count", run.base_commit) == "1"


def test_a_folder_inside_another_repository_and_a_detached_head_are_refused(repo, tmp_path):
    inner = repo / "sub"
    inner.mkdir()
    with pytest.raises(PrototypeError, match="inside the git repository"):
        prototypes.start(inner, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert not (inner / ".git").exists() and not (tmp_path / "home").exists()
    prototypes.git(repo, "checkout", "--detach")
    with pytest.raises(PrototypeError, match="detached HEAD"):
        prototypes.start(repo, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert branches(repo).keys() == {"refs/heads/main", "refs/heads/feature"}


def test_without_git_it_says_so_and_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(prototypes, "git_binary", lambda: None)
    with pytest.raises(PrototypeError, match="git is not installed"):
        prototypes.start(tmp_path / "p", tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert not (tmp_path / "p").exists() and not (tmp_path / "home").exists()
    with pytest.raises(PrototypeError, match="two approaches"):
        prototypes.start(tmp_path / "p", tmp_path / "home", "t", [blueprint("A")], shared_tests())


def test_a_folder_too_big_to_snapshot_is_refused(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    big = tmp_path / "big"
    big.mkdir()
    (big / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(prototypes, "MAX_SNAPSHOT_FILES", 0)
    with pytest.raises(PrototypeError, match="too much"):
        prototypes.start(big, tmp_path / "home", "t", [blueprint("A"), blueprint("B")], shared_tests())
    assert not (big / ".git").exists()


def test_the_project_file_list_does_not_show_a_repository(tmp_path):
    files = ProjectFiles(tmp_path)
    files.write("p1", "notes.md", b"hi")
    (files.folder("p1") / ".git" / "objects").mkdir(parents=True)
    (files.folder("p1") / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert files.list("p1") == [{"path": "notes.md", "size": 2}]


# ---------------------------------------------------------------- the tests and checks
def test_the_shared_tests_are_validated():
    ok = prototypes.clean_tests({"files": {"t/test_a.py": "x = 1\n"}, "checks": [
        {"kind": "contains", "path": "out.md", "all": ["uno", " "]}, {"kind": "words_max", "path": "out.md", "max": 50},
        {"kind": "unittest", "start": "t", "pattern": "test_*.py"}, {"kind": "python", "code": "assert True"}]})
    assert ok["files"] == {"t/test_a.py": "x = 1\n"} and ok["checks"][0]["all"] == ["uno"]
    assert ok["checks"][2] == {"kind": "unittest", "name": "", "start": "t", "pattern": "test_*.py"}
    assert prototypes.clean_tests(None) == {"files": {}, "checks": []}
    default = prototypes.default_tests(prototypes.clean_tests({"files": {"t/test_a.py": "x"}}))
    assert default["checks"] == [{"kind": "unittest", "name": "", "start": "t", "pattern": "test*.py"}]
    for bad in ("text", {"files": []}, {"other": 1}, {"files": {"../x.py": "x"}}, {"files": {"/abs.py": "x"}},
                {"files": {"a.py": 5}}, {"files": {"a.py": "x" * 100_001}}, {"files": {f"{i}.py": "" for i in range(6)}},
                {"checks": [{"kind": "shell", "code": "rm -rf /"}]}, {"checks": [{"kind": "python", "code": " "}]},
                {"checks": [{"kind": "unittest", "pattern": "../*.py"}]}, {"checks": [{"kind": "unittest", "start": ".."}]},
                {"checks": [{"kind": "contains", "path": "a.md", "all": []}]},
                {"checks": [{"kind": "words_max", "path": "a.md", "max": True}]},
                {"checks": [{"kind": "contains", "path": "../a.md", "all": ["x"]}]},
                {"checks": [{"kind": "python", "code": "x"}] * 13}):
        with pytest.raises(ValueError):
            prototypes.clean_tests(bad)


def test_the_comparison_follows_the_numbers_and_leaves_ties_open():
    def result(passed, checks, status="built"):
        return {"status": status, "tests": {"ran": True, "passed": passed, "total": 4},
                "checks": {"passed": checks, "total": 3}, "files": {"count": 1, "insertions": 2, "deletions": 0},
                "seconds": {"total": 1.5}}

    assert prototypes.compare({"a": result(3, 0), "b": result(4, 0)})["leader"] == "b"
    assert prototypes.compare({"a": result(4, 1), "b": result(4, 3)}) == {
        "rows": prototypes.compare({"a": result(4, 1), "b": result(4, 3)})["rows"], "leader": "b", "basis": "checks"}
    assert prototypes.compare({"a": result(4, 2), "b": result(4, 2)})["leader"] is None
    assert prototypes.compare({"a": result(2, 3), "b": result(3, 0)})["leader"] == "b"  # tests first, then checks
    assert prototypes.compare({"a": result(1, 1)})["leader"] is None


def test_unittest_counts_are_read_from_what_the_run_printed():
    out = 'noise\n{"spike_tests": {"run": 3, "failed": 1, "errors": 0, "skipped": 0, "bad": ["t (m.C.t)"]}}\nFAIL...\n'
    assert prototypes.parse_unittest(out)["run"] == 3 and prototypes.parse_unittest("Traceback...\nImportError") == {}
    assert prototypes.parse_unittest('{"spike_tests": nope}') == {}


async def checked(root, checks_spec, broker=ALLOWED, files=None, deliverables=()):
    for rel, content in {**(checks_spec.get("files") or {}), **(files or {})}.items():  # as `start` and the build do
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    box: list = []
    spec = prototypes.default_tests(prototypes.clean_tests(checks_spec))
    events = [e async for e in prototypes.run_checks(root, spec, default_registry(root), broker, list(deliverables),
                                                     {"proto": "a"}, box)]
    return box[0], events


async def test_every_kind_of_check_runs_on_the_checkout(tmp_path):
    result, _ = await checked(tmp_path, {"files": {}, "checks": [
        {"kind": "contains", "path": "r.md", "all": ["alfa", "beta"]}, {"kind": "contains", "path": "r.md", "all": ["gamma"]},
        {"kind": "words_max", "path": "r.md", "max": 5}, {"kind": "python", "code": "import r_mod\nassert r_mod.X == 1"},
        {"kind": "python", "code": "raise SystemExit(3)"}]}, files={"r.md": "alfa beta delta", "r_mod.py": "X = 1\n"},
        deliverables=[{"path": "r.md", "ok": True}, {"path": "gone.md", "ok": False},
                      {"path": "bad.py", "ok": True, "program": {"ok": False, "note": "raised NameError"}}])
    assert [(i["kind"], i["ok"]) for i in result["checks"]["items"]] == [
        ("deliverable", True), ("deliverable", False), ("deliverable", False), ("contains", True), ("contains", False),
        ("words_max", True), ("python", True), ("python", False)]
    assert result["checks"]["items"][1]["note"] == "not saved" and "NameError" in result["checks"]["items"][2]["note"]
    assert (result["checks"]["passed"], result["checks"]["total"]) == (4, 8)
    assert result["tests"]["ran"] is False and result["tests"]["reason"] == "no tests"


async def test_the_code_of_a_check_runs_in_a_copy_and_the_checkout_stays_as_it_was(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")  # a checkout's own pointer: never copied
    result, _ = await checked(tmp_path, {"checks": [{"kind": "python", "code": (
        "import os\nassert not os.path.exists('.git')\nopen('made.txt', 'w').write('x')\n"
        "open('keep.txt', 'w').write('changed')")}]}, files={"keep.txt": "original"})
    assert result["checks"]["items"][0]["ok"] is True
    assert not (tmp_path / "made.txt").exists() and (tmp_path / "keep.txt").read_text(encoding="utf-8") == "original"


async def test_nothing_runs_when_the_user_refuses_the_python_tool(tmp_path):
    spec = {"files": {"t/test_ok.py": "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                                      "        self.assertTrue(True)\n"},
            "checks": [{"kind": "python", "code": "print(1)"}, {"kind": "contains", "path": "n.md", "all": ["si"]}]}
    result, events = await checked(tmp_path, spec, PermissionBroker({"python": "deny"}), files={"n.md": "si"})
    assert result["tests"]["ran"] is False and "disabled" in result["tests"]["reason"] and result["tests"]["total"] == 0
    assert [(i["kind"], i["ok"]) for i in result["checks"]["items"]] == [("python", False), ("contains", True)]
    asked = PermissionBroker({"python": "ask"}, timeout_s=0.05)  # nobody answers: it is a no
    result, events = await checked(tmp_path, spec, asked, files={"n.md": "si"})
    request = next(e for e in events if e["type"] == "permission_request")
    assert request["tool"] == "python" and request["proto"] == "a"  # the question carries which prototype asks
    assert result["tests"]["ran"] is False and "denied" in result["tests"]["reason"]


async def test_a_suite_that_cannot_be_loaded_is_zero_tests_passed_not_a_crash(tmp_path):
    result, _ = await checked(tmp_path, {"files": {"t/test_x.py": "import nothing_here_exists\n"}})
    tests_ = result["tests"]
    assert tests_["ran"] is True and tests_["passed"] == 0 and tests_["total"] == 1 and len(tests_["failed"]) == 1
    result, _ = await checked(tmp_path / "syntax", {"files": {"t/test_y.py": "def (:\n"}})
    assert result["tests"]["passed"] == 0 and result["tests"]["ran"] is True


async def test_a_run_without_the_python_tool_reports_why(tmp_path):
    box: list = []
    spec = prototypes.default_tests(prototypes.clean_tests({"files": {"t/test_a.py": "x = 1\n"}}))
    _ = [e async for e in prototypes.run_checks(tmp_path, spec, ToolRegistry([]), ALLOWED, [], {}, box)]
    assert box[0]["tests"]["ran"] is False and "not available" in box[0]["tests"]["reason"]


# ---------------------------------------------------------------- through the app
DRAFTS = {label: {"goal": f"Slug {label}", "requirements": ["slugify(text)"], "criteria": ["slugify exists"], "steps": [
    {"id": "t1", "specialist": "code", "role": "execute", "instruction": f"Guarda slug.py (enfoque {label})",
     "depends_on": [], "deliverables": ["slug.py"]}]} for label in ("A", "B")}


def model(request):
    """The model of the app tests: drafts each approach's blueprint, saves each approach's file, passes the checker."""
    blob = "\n".join(m.content for m in request.messages if m.content)
    label = "B" if "Approach B" in blob or "enfoque B" in blob else "A"
    if request.json_schema and "steps" in request.json_schema["properties"]:
        return text(json.dumps(DRAFTS[label]))
    if request.json_schema:
        return text(json.dumps({"results": [], "criteria": [{"n": 1, "ok": True, "note": ""}]}))
    if request.messages[-1].role == "tool":
        return text("Guardé slug.py")
    return call("write_file", {"path": "slug.py", "content": FILES[label.lower()]["slug.py"]})


@pytest.fixture
def app(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    providers: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = providers.setdefault(cfg.id, ScriptedProvider(model, name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    state.broker.policies.update({"write_file": "allow", "python": "allow"})
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, state, providers["spike-local"], tmp_path


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def start_body(**extra) -> dict:
    return {"task": "Haz slugify", "blueprints": [DRAFTS["A"], DRAFTS["B"]], "tests": TESTS, **extra}


def test_drafting_gives_one_blueprint_per_approach_and_runs_nothing(app):
    client, _, local, home = app
    r = client.post("/api/forge/prototypes/blueprints", json={"task": "Haz slugify"})
    assert r.status_code == 200
    drafted = r.json()["approaches"]
    assert [d["label"] for d in drafted] == ["a", "b"] and drafted[0]["blueprint"]["goal"] == "Slug A"
    assert drafted[1]["blueprint"]["steps"][0]["deliverables"] == ["slug.py"]
    prompts = ["\n".join(m.content for m in rq.messages) for rq in local.requests]
    assert "Approach A" in prompts[0] and "Approach B" in prompts[1] and "Approach B" not in prompts[0]
    assert not (home / "ws" / ".git").exists() and not (home / "prototypes").exists()
    assert client.post("/api/forge/prototypes/blueprints", json={"task": "x", "provider_id": "nope"}).status_code == 400


def test_the_app_builds_compares_and_merges_only_what_the_user_approves(app):
    client, state, _, home = app
    ws = home / "ws"
    listed = client.get("/api/forge/prototypes").json()
    assert listed["git"] is True and listed["runs"] == []
    r = client.post("/api/forge/prototypes", json=start_body())
    assert r.status_code == 200
    events = sse(r)
    assert events[0]["type"] == "proto_start" and events[-1]["type"] == "proto_compare"
    assert events[-1]["leader"] == "a" and events[-1]["basis"] == "tests"
    assert {e["proto"] for e in events if e["type"] in ("subtask_start", "forge_report", "done")} == {"a", "b"}
    results = {e["proto"]: e for e in events if e["type"] == "proto_result"}
    assert (results["a"]["tests"]["passed"], results["b"]["tests"]["passed"], results["b"]["tests"]["total"]) == (3, 2, 3)
    run_id = events[0]["id"]

    assert (ws / ".git").exists() and not (ws / "slug.py").exists()  # a repository was made; nothing built in the folder
    assert sorted(branches(ws)) == ["refs/heads/" + b for b in sorted(
        [f"spike/proto-{run_id}-a", f"spike/proto-{run_id}-b", sh(ws, "rev-parse", "--abbrev-ref", "HEAD")])]
    runs = client.get("/api/forge/prototypes").json()["runs"]
    assert [(r["id"], r["status"]) for r in runs] == [(run_id, "built")] and "root" not in runs[0]
    assert client.get(f"/api/forge/prototypes/{run_id}").json()["comparison"]["leader"] == "a"
    assert client.get("/api/forge/prototypes/deadbeef").status_code == 404
    odd = client.get("/api/forge/prototypes/..%2F..")  # not a run id (a built web app answers unknown paths with its page)
    assert odd.status_code in (404, 422) or "json" not in odd.headers["content-type"]
    with pytest.raises(PrototypeError):
        prototypes.load(state.prototypes_home, "../..")

    head = sh(ws, "rev-parse", "HEAD")
    nope = client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "a"})  # no approval
    assert nope.status_code == 403 and sh(ws, "rev-parse", "HEAD") == head and not (ws / "slug.py").exists()
    assert client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "c", "approve": True}).status_code == 422
    merged = client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "a", "approve": True})
    assert merged.status_code == 200 and merged.json()["run"]["status"] == "merged"
    assert (ws / "slug.py").read_text(encoding="utf-8") == SLUG_A
    assert client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "b", "approve": True}).status_code == 409
    assert client.post(f"/api/forge/prototypes/{run_id}/discard").status_code == 409
    assert client.get("/api/forge/prototypes").json()["runs"][0]["status"] == "merged"


def test_discarding_a_run_through_the_app_removes_its_branches(app):
    client, _, _, home = app
    ws = home / "ws"
    run_id = sse(client.post("/api/forge/prototypes", json=start_body()))[0]["id"]
    users = users_branches(ws)
    assert client.post(f"/api/forge/prototypes/{run_id}/discard").status_code == 200
    assert "spike/proto" not in sh(ws, "branch", "--list") and users_branches(ws) == users and checkouts(ws) == 1
    assert client.get(f"/api/forge/prototypes/{run_id}").json()["status"] == "discarded"
    assert client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "a", "approve": True}).status_code == 409


def test_a_run_whose_stream_is_gone_is_interrupted_and_can_only_be_discarded(app):
    client, state, _, home = app
    ws = home / "ws"
    run_id = sse(client.post("/api/forge/prototypes", json=start_body()))[0]["id"]
    record = state.prototypes_home / run_id / "run.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["status"] = "building"  # as left by a server that stopped mid-build
    record.write_text(json.dumps(data), encoding="utf-8")
    assert client.get(f"/api/forge/prototypes/{run_id}").json()["status"] == "interrupted"
    assert client.get("/api/forge/prototypes").json()["runs"][0]["status"] == "interrupted"
    assert client.post(f"/api/forge/prototypes/{run_id}/merge", json={"choice": "a", "approve": True}).status_code == 409
    assert not (ws / "slug.py").exists()
    assert client.post(f"/api/forge/prototypes/{run_id}/discard").status_code == 200


def test_a_project_builds_in_its_own_folder_and_its_repository_is_not_one_of_its_files(app):
    client, state, _, home = app
    pid = client.post("/api/projects", json={"name": "Sitio"}).json()["id"]
    client.put(f"/api/projects/{pid}/files/notas.md", content=b"hola")
    r = client.post("/api/forge/prototypes", json=start_body(project_id=pid))
    assert r.status_code == 200 and sse(r)[-1]["type"] == "proto_compare"
    folder = state.project_files.folder(pid)
    assert (folder / ".git").exists() and not (home / "ws" / ".git").exists() and not (folder / "slug.py").exists()
    assert [f["path"] for f in client.get(f"/api/projects/{pid}/files").json()] == ["notas.md"]
    assert len(client.get(f"/api/forge/prototypes?project_id={pid}").json()["runs"]) == 1
    assert client.get("/api/forge/prototypes").json()["runs"] == []  # the workspace has none
    assert client.get("/api/forge/prototypes?project_id=nope").status_code == 400
    assert len(list((state.prototypes_home).glob("*/run.json"))) == 1
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert list(state.prototypes_home.glob("*/run.json")) == [] and not folder.exists()


def test_a_request_that_cannot_work_is_refused_before_any_folder_or_branch_is_made(app):
    client, state, _, home = app
    ws = home / "ws"

    def refused(code, **change):
        body = {**start_body(), **change}
        r = client.post("/api/forge/prototypes", json=body)
        assert r.status_code == code, r.text
        assert not (ws / ".git").exists() and not state.prototypes_home.exists()
        return r

    refused(422, blueprints=[DRAFTS["A"]])
    refused(422, blueprints=[DRAFTS["A"], DRAFTS["B"], DRAFTS["A"]])
    refused(422, task="")
    refused(400, blueprints=[DRAFTS["A"], {"goal": "x", "steps": [{"id": "t1", "specialist": "nope", "instruction": "x"}]}])
    refused(400, blueprints=[DRAFTS["A"], {**DRAFTS["B"], "steps": [{**DRAFTS["B"]["steps"][0], "deliverables": []}]}])
    refused(400, tests={"files": {"../escape.py": "x"}})
    refused(400, tests={"checks": [{"kind": "shell", "code": "ls"}]})
    refused(400, provider_id="nope")
    refused(400, project_id="nope")
    assert client.put("/api/settings", json={"tools_enabled": False}).status_code == 200
    assert "needs tools" in refused(400).json()["detail"]


def test_the_paid_call_guard_applies_before_anything_is_created(app):
    client, state, _, home = app
    body = {"preset": "openai", "api_key": "sk-test", "model": "gpt-test", "allow_paid": False}
    assert client.post("/api/providers", json=body).status_code == 200
    r = client.post("/api/forge/prototypes", json=start_body(provider_id="openai"))
    assert r.status_code == 403 and "may bill your account" in r.json()["detail"]
    assert not (home / "ws" / ".git").exists() and not state.prototypes_home.exists()


def test_without_git_the_app_says_so(app, monkeypatch):
    client, state, _, home = app
    monkeypatch.setattr(prototypes, "git_binary", lambda: None)
    assert client.get("/api/forge/prototypes").json()["git"] is False
    r = client.post("/api/forge/prototypes", json=start_body())
    assert r.status_code == 400 and "git is not installed" in r.json()["detail"] and not state.prototypes_home.exists()


def test_it_is_off_unless_asked_for_an_ordinary_forge_chat_makes_no_branches(app):
    client, state, _, home = app
    r = client.post("/api/chat", json={"message": "Haz slugify", "forge": DRAFTS["A"]})
    assert r.status_code == 200 and (home / "ws" / "slug.py").read_text(encoding="utf-8") == SLUG_A
    assert not (home / "ws" / ".git").exists() and not state.prototypes_home.exists()
    assert client.get("/api/forge/prototypes").json()["runs"] == []
