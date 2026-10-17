"""`spike dev`: its tools, a session with a scripted model (asks, undo, history, resume) and the terminal."""

from __future__ import annotations

import asyncio
import io
import sys
import time

import pytest

from spike.cli import main as cli
from spike.dev import terminal
from spike.dev.session import DEV_INSTRUCTIONS, DevSession
from spike.dev.tools import MAX_OUTPUT, RUNNING, EditFile, FindFiles, RunCommand, SearchFiles, stop_commands
from spike.server.state import AppState
from spike.store.checkpoints import CheckpointError
from spike.tools.builtin import Workspace
from tests.helpers import ScriptedProvider, call, text


# ---------------------------------------------------------------- tools
@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "pkg" / "util.py").write_text("X = 1\nx = 2\nX = 3\n", encoding="utf-8")
    (root / "node_modules" / "dep" / "index.py").write_text("X = 9\n", encoding="utf-8")
    (root / ".git" / "config.py").write_text("X = 0\n", encoding="utf-8")
    return Workspace(root)


async def test_edit_file_replaces_one_exact_match(ws):
    tool = EditFile(ws)
    ok = await tool.run({"path": "calc.py", "old": "a - b", "new": "a + b"})
    assert ok.ok and ok.data == {"file": "calc.py"}
    assert (ws.root / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    twice = await tool.run({"path": "pkg/util.py", "old": "X = ", "new": "Y = "})
    assert not twice.ok and "appears 2 times" in twice.content
    assert (ws.root / "pkg/util.py").read_text() == "X = 1\nx = 2\nX = 3\n"
    every = await tool.run({"path": "pkg/util.py", "old": "X = ", "new": "Y = ", "replace_all": True})
    assert every.ok and "2 changes" in every.content
    assert (ws.root / "pkg/util.py").read_text() == "Y = 1\nx = 2\nY = 3\n"
    assert "not found" in (await tool.run({"path": "calc.py", "old": "zzz", "new": ""})).content
    assert "empty" in (await tool.run({"path": "calc.py", "old": "", "new": "x"})).content
    outside = await tool.run({"path": "../evil.py", "old": "a", "new": "b"})
    assert not outside.ok and "outside the workspace" in outside.content
    assert tool.targets({"path": "calc.py"}) == [ws.root / "calc.py"] and tool.targets({"path": "../x"}) == []


async def test_run_command_reports_exit_code_output_and_limits(ws):
    tool = RunCommand(ws)
    ok = await tool.run({"command": "pwd && echo hola"})
    assert ok.ok and ok.content.splitlines() == ["exit code 0", str(ws.root), "hola"]
    failed = await tool.run({"command": "echo boom >&2; exit 3"})
    assert not failed.ok and failed.content == "exit code 3\nboom"
    started = time.perf_counter()
    slow = await tool.run({"command": "sleep 30", "timeout_s": 1})
    assert not slow.ok and "timed out after 1 s" in slow.content and time.perf_counter() - started < 10
    big = await tool.run({"command": f"{sys.executable} -c \"print('x' * {MAX_OUTPUT * 2})\""})
    assert big.ok and "chars cut" in big.content and len(big.content) < MAX_OUTPUT + 200
    assert not (await tool.run({"command": "  "})).ok


async def test_a_stopped_request_or_exit_stops_its_command(ws):
    tool = RunCommand(ws)
    stopped = asyncio.create_task(tool.run({"command": "sleep 1.5; touch stopped"}))
    await asyncio.sleep(0.4)
    stopped.cancel()  # Ctrl-C
    with pytest.raises(asyncio.CancelledError):
        await stopped
    left = asyncio.create_task(tool.run({"command": "sleep 1.5; touch left"}))
    await asyncio.sleep(0.4)
    assert len(RUNNING) == 1
    stop_commands()  # `spike dev` leaving (exit, closed terminal)
    assert not (await left).ok and not RUNNING
    await asyncio.sleep(2)
    assert not (ws.root / "stopped").exists() and not (ws.root / "left").exists()


async def test_search_and_find_skip_dependencies_and_vcs(ws):
    search = SearchFiles(ws)
    hits = (await search.run({"pattern": r"^X = \d"})).content.splitlines()
    assert hits == ["pkg/util.py:1: X = 1", "pkg/util.py:3: X = 3"]
    assert len((await search.run({"pattern": "^x =", "ignore_case": True})).content.splitlines()) == 3
    assert (await search.run({"pattern": "return", "glob": "*.md"})).content == "no matches"
    assert (await search.run({"pattern": "return", "glob": "*.py"})).content == "calc.py:2:     return a - b"
    bad = await search.run({"pattern": "("})
    assert not bad.ok and "invalid pattern" in bad.content
    find = FindFiles(ws)
    assert (await find.run({"glob": "**/*.py"})).content.splitlines() == ["calc.py", "pkg/util.py"]
    assert (await find.run({"glob": "pkg/*"})).content == "pkg/util.py"
    assert (await find.run({"glob": "*.rs"})).content == "no files"


# ---------------------------------------------------------------- the session
@pytest.fixture
def dev(tmp_path, monkeypatch, ws):
    for name, value in (("SPIKE_HOME", tmp_path / "home"), ("SPIKE_WORKSPACE", tmp_path / "app-ws"),
                        ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path / "home", provider_factory=factory)
    (ws.root / "AGENTS.md").write_text("Run tests with: python -m pytest -q\n", encoding="utf-8")
    return state, local, ws.root


async def collect(session, text_):
    return [ev async for ev in session.turn(text_)]


async def test_a_session_asks_edits_keeps_history_and_undoes(dev):
    state, local, root = dev
    asked = []

    def decide(ev):
        asked.append(ev["tool"])
        return "allow_once" if ev["tool"] == "edit_file" else "deny"

    session = DevSession(state, root, decide=decide)
    local._script = [
        call("edit_file", {"path": "calc.py", "old": "a - b", "new": "a + b"}, "c1"),
        call("run_command", {"command": "python -m pytest -q"}, "c2"),
        text("Fixed add in calc.py; I could not run the tests."),
        text("Nothing else to do."),
    ]
    events = await collect(session, "fix the bug in calc.py")
    assert asked == ["edit_file", "run_command"]
    assert (root / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    results = {ev["id"]: ev for ev in events if ev["type"] == "tool_result"}
    assert results["c1"]["ok"] and results["c1"]["checkpoint"]
    assert not results["c2"]["ok"] and "denied" in results["c2"]["content"]
    assert any(ev["type"] == "skill" and "systematic-debugging" in ev["names"] for ev in events)
    first = local.requests[0]
    system = first.messages[0].content
    assert DEV_INSTRUCTIONS.format(root=root) in system and "Run tests with: python -m pytest -q" in system
    assert {"edit_file", "run_command", "search", "find_files", "read_file", "write_file"} <= {t.name for t in first.tools}

    await collect(session, "anything else?")
    seen = [m.content for m in local.requests[-1].messages if m.role in ("user", "assistant")]
    assert seen[-3:] == ["fix the bug in calc.py", "Fixed add in calc.py; I could not run the tests.", "anything else?"]

    assert [c["tool"] for c in session.changes()] == ["edit_file"]
    assert session.undo_last()["undone"]
    assert (root / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"
    with pytest.raises(CheckpointError) as nothing:
        session.undo_last()
    assert nothing.value.status == 400

    again = DevSession(state, root, resume=True)
    assert [m.content for m in again.history][-1] == "Nothing else to do."
    fresh = DevSession(state, root)
    assert fresh.history == [] and len(fresh.changes()) == 1  # undo reaches every session of the folder


async def test_undo_refuses_to_lose_later_changes_unless_forced(dev):
    state, local, root = dev
    session = DevSession(state, root, accept_edits=True, decide=lambda ev: pytest.fail("edits were allowed"))
    local._script = [call("edit_file", {"path": "calc.py", "old": "a - b", "new": "a * b"}), text("done")]
    await collect(session, "multiply instead")
    (root / "calc.py").write_text("changed by hand\n", encoding="utf-8")
    with pytest.raises(CheckpointError) as later:
        session.undo_last()
    assert later.value.status == 409 and later.value.changed == [str(root / "calc.py")]
    session.undo_last(force=True)
    assert (root / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


async def test_a_stopped_request_keeps_what_was_written(dev):
    state, local, root = dev
    session = DevSession(state, root)
    local._script = [text("Looking at ", "the code…")]
    run = session.turn("explain calc.py")
    while (await run.__anext__())["type"] != "delta":
        pass
    await run.aclose()
    stored = session.store.messages(session.conversation_id)
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"] == "Looking at " and stored[1]["meta"]["stopped"]


async def test_questions_get_an_answer_or_a_note_when_nobody_can(dev):
    state, local, root = dev
    session = DevSession(state, root)
    local._script = [call("ask_user", {"question": "Which file?", "options": ["a", "b"]}), text("ok")]
    await collect(session, "change it")
    tool_msg = next(m for m in local.requests[-1].messages if m.role == "tool")
    assert "nobody can answer here" in tool_msg.content
    session.answer = lambda ev: ev["options"][1]
    local._script = [call("ask_user", {"question": "Which file?", "options": ["a", "b"]}), text("ok")]
    await collect(session, "change it again")
    assert next(m for m in reversed(local.requests[-1].messages) if m.role == "tool").content == "The user answered: b"


def test_a_session_needs_a_folder_and_a_known_specialist(dev, tmp_path):
    state, _, root = dev
    with pytest.raises(FileNotFoundError):
        DevSession(state, tmp_path / "missing")
    with pytest.raises(KeyError):
        DevSession(state, root, specialist="nobody")


# ---------------------------------------------------------------- the terminal
def test_previews_show_the_diff_or_the_command(ws):
    edit = terminal.preview({"tool": "edit_file", "arguments": {"path": "calc.py", "old": "    return a - b",
                                                               "new": "    return a + b"}}, ws.root)
    assert edit[2:] == ["@@ -1,2 +1,2 @@", " def add(a, b):", "-    return a - b", "+    return a + b"]
    stale = terminal.preview({"tool": "edit_file", "arguments": {"path": "calc.py", "old": "gone", "new": "x"}}, ws.root)
    assert "-gone" in stale and "+x" in stale  # not in the file: the edit's own text
    new = terminal.preview({"tool": "write_file", "arguments": {"path": "n.py", "content": "a\nb"}}, ws.root)
    assert new == ["new file n.py (2 lines)", "+a", "+b"]
    over = terminal.preview({"tool": "write_file", "arguments": {"path": "calc.py", "content": "x\n"}}, ws.root)
    assert "-def add(a, b):" in over and "+x" in over
    cmd = terminal.preview({"tool": "run_command", "arguments": {"command": "rm -rf build"}}, ws.root)
    assert cmd[0] == "$ rm -rf build" and "cannot be undone" in cmd[1]


def test_the_prompt_takes_yes_always_and_no(ws):
    replies = iter(["a", "y", "", "maybe", "n", "2", "free text"])
    decide, answer = terminal.prompter(terminal.Out(io.StringIO()), ws.root, lambda _: next(replies))
    ev = {"tool": "run_command", "arguments": {"command": "ls"}}
    assert decide(ev) == "allow_always"
    assert decide({**ev, "once": True}) == "allow_once"  # "always" is not offered for this one
    assert decide(ev) == "deny"
    assert decide(ev) == "deny"  # an unclear reply asks again, then "n"
    assert answer({"question": "Which?", "options": ["a", "b"]}) == "b"
    assert answer({"question": "Which?", "options": []}) == "free text"


def test_the_repl_runs_requests_and_slash_commands(dev):
    state, local, root = dev
    stream = io.StringIO()
    out = terminal.Out(stream)
    lines = iter(["/help", "fix calc", "/steps", "/undo", "/undo", "/clear", "/nope", "/exit"])
    session = DevSession(state, root, accept_edits=True)
    local._script = [call("edit_file", {"path": "calc.py", "old": "a - b", "new": "a + b"}), text("Fixed.")]
    loop = asyncio.new_event_loop()
    try:
        assert terminal.repl(loop, session, out, lambda _: next(lines)) == 0
    finally:
        loop.close()
    shown = stream.getvalue()
    assert "/undo   put back" in shown and "→ edit_file calc.py" in shown and "✓ edited calc.py" in shown
    assert "Fixed." in shown and "  1. edit_file   calc.py" in shown
    assert "Put back: calc.py" in shown and "nothing to undo" in shown and "unknown command /nope" in shown
    assert (root / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_the_cli_checks_its_arguments(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    assert cli(["dev", str(tmp_path / "missing")]) == 2
    assert cli(["dev", str(tmp_path), "--specialist", "nobody"]) == 2
    assert cli(["dev", str(tmp_path), "--provider", "nobody"]) == 2
    err = capsys.readouterr().err
    assert "is not a folder" in err and "unknown specialist 'nobody'" in err and "unknown provider 'nobody'" in err
