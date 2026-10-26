"""OS isolation of the code-running tools: the command lines (pure, on every OS), detection and wrapping with fake
`bwrap` / `sandbox-exec` programs, the three settings, the permission card and, only where the real program works on
the machine running the tests, proof that a wrapped script cannot write outside its folder or reach the network."""

from __future__ import annotations

import asyncio
import io
import os
import socket
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.agent.loop import AgentRun, run_agent
from spike.core.types import Message
from spike.dev import terminal
from spike.dev.tools import RunCommand, _kill
from spike.orchestrator.verify import run_outcome
from spike.server.app import create_app
from spike.server.state import AppState
from spike.tools.base import PermissionBroker
from spike.tools.builtin import PythonRunner, Workspace, default_registry
from spike.tools.sandbox import (
    ETC_ENTRIES,
    MODES,
    NOTE,
    Isolation,
    Sandbox,
    SandboxRefused,
    bwrap_argv,
    interpreter_dirs,
    sbpl_quote,
    seatbelt_profile,
    strip_note,
    system_layout,
    was_isolated,
    with_note,
)
from tests.helpers import ScriptedProvider, call, text

posix = pytest.mark.skipif(os.name == "nt", reason="the fake sandbox programs are shell scripts")
NONE = Sandbox("auto", platform="win32")  # a computer with no sandbox, whatever machine runs the tests


# ---------------------------------------------------------------- command lines (pure)
def test_seatbelt_profile_denies_everything_then_allows_only_what_it_is_given():
    profile = seatbelt_profile(readable=["/opt/py"], writable=["/work/proj", "/tmp/private"])
    lines = profile.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"]
    assert "(deny network*)" in lines and not any("allow network" in line for line in lines)
    writes = next(line for line in lines if line.startswith("(allow file-write* ("))
    assert writes == '(allow file-write* (subpath "/work/proj") (subpath "/tmp/private"))'
    reads = next(line for line in lines if line.startswith("(allow file-read* (subpath"))
    for path in ("/usr", "/System", "/opt/py", "/work/proj", "/tmp/private"):
        assert f'(subpath "{path}")' in reads
    assert "/Users" not in profile and "/home" not in profile  # the home folder is not readable
    assert '(literal "/dev/null")' in profile and "process-exec" in profile
    twice = seatbelt_profile(readable=["/a", "/a"], writable=["/w", "/w"])
    assert twice.count('(subpath "/w")') == 2 and twice.count('(subpath "/a")') == 1  # read + write; each path once


def test_seatbelt_profile_quotes_paths_and_refuses_control_characters():
    assert sbpl_quote('/my "dir"\\x') == '"/my \\"dir\\"\\\\x"'
    assert '(subpath "/a \\"b\\"")' in seatbelt_profile(readable=[], writable=['/a "b"'])
    with pytest.raises(ValueError):
        sbpl_quote("/a\n(allow default)")


def test_bwrap_argv_has_no_network_a_private_tmp_and_only_the_given_folders_writable():
    argv = bwrap_argv(["/usr/bin/python3", "-I", "main.py"], binary="/usr/bin/bwrap",
                      system=[("/usr", None), ("/bin", "usr/bin"), ("/lib64", "usr/lib64")], etc=["passwd", "alternatives"],
                      readable=["/opt/venv", "/work/proj/.venv"], writable=["/work/proj"], cwd="/work/proj")
    assert argv[0] == "/usr/bin/bwrap"
    for flag in ("--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid", "--unshare-ipc"):
        assert flag in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--tmpfs"):argv.index("--tmpfs") + 2] == ["--tmpfs", "/tmp"]
    pairs = [tuple(argv[i:i + 3]) for i in range(len(argv) - 2)]
    assert ("--ro-bind", "/usr", "/usr") in pairs
    assert ("--symlink", "usr/bin", "/bin") in pairs and ("--symlink", "usr/lib64", "/lib64") in pairs
    assert ("--ro-bind-try", "/etc/passwd", "/etc/passwd") in pairs
    assert ("--ro-bind-try", "/etc/alternatives", "/etc/alternatives") in pairs
    assert [a for a, b, c in pairs if a == "--bind"] == ["--bind"] and ("--bind", "/work/proj", "/work/proj") in pairs
    assert ("--ro-bind", "/opt/venv", "/opt/venv") in pairs
    # a read-only folder inside the writable one is mounted after it, so it stays read-only
    assert argv.index("/work/proj/.venv") > argv.index("--bind")
    assert argv[-6:] == ["--chdir", "/work/proj", "--", "/usr/bin/python3", "-I", "main.py"][-6:]
    assert argv[argv.index("--") + 1:] == ["/usr/bin/python3", "-I", "main.py"]
    assert "--share-net" not in argv


def test_bwrap_argv_binds_nothing_it_was_not_given():
    argv = bwrap_argv(["true"], binary="bwrap", system=[], etc=[], readable=[], writable=["/w"], cwd="/w")
    assert [a for a in argv if a in ("--ro-bind", "--symlink", "--ro-bind-try")] == []
    assert argv.count("--bind") == 1 and "/home" not in argv and "/root" not in argv


@pytest.mark.skipif(os.name == "nt", reason="symlinks need a privilege on Windows")
def test_system_layout_keeps_host_symlinks_and_lists_only_what_exists(tmp_path):
    (tmp_path / "usr/bin").mkdir(parents=True)
    (tmp_path / "usr/lib").mkdir(parents=True)
    (tmp_path / "bin").symlink_to("usr/bin")
    (tmp_path / "lib").symlink_to("usr/lib")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/passwd").write_text("root:x:0:0\n", encoding="utf-8")
    (tmp_path / "etc/shadow").write_text("secret\n", encoding="utf-8")
    system, etc = system_layout(str(tmp_path))
    assert system == [("/usr", None), ("/bin", "usr/bin"), ("/lib", "usr/lib")]
    assert etc == ["passwd"] and "shadow" not in ETC_ENTRIES


def test_the_interpreter_folders_are_listed_and_never_the_whole_disk():
    found = interpreter_dirs()
    assert os.path.abspath(sys.prefix) in found and os.path.abspath(sys.base_prefix) in found
    assert os.path.abspath(os.sep) not in found and all(os.path.isabs(p) for p in found)


def test_the_note_is_added_and_removed_from_a_result():
    on = Isolation(True, "bwrap")
    off = Isolation(False, "none", "bubblewrap (bwrap) is not installed", "no_bwrap")
    assert with_note("4", on) == (f"4\n{NOTE}isolated (bwrap): no network, writes only in the working folder and a "
                                  "private temp folder]")
    assert with_note("4", off) == f"4\n{NOTE}not isolated: bubblewrap (bwrap) is not installed]"
    assert strip_note(with_note("a\nb", on)) == "a\nb"
    assert strip_note("[sandbox: but not the last line]\nx") == "[sandbox: but not the last line]\nx"
    assert strip_note("4") == "4" and off.to_dict()["code"] == "no_bwrap" and on.to_dict()["isolated"] is True


def test_a_program_check_ignores_the_note_when_it_reads_the_traceback():
    trace = "Traceback (most recent call last):\n  File \"main.py\", line 1\nModuleNotFoundError: No module named 'x'"
    noted = with_note(trace, Isolation(False, "none", "the sandbox is off in Settings", "off"))
    plain = run_outcome("a.py", ["a.py"], trace, False, "compiles")
    assert run_outcome("a.py", ["a.py"], noted, False, "compiles") == plain
    assert run_outcome("a.py", ["a.py"], noted, False, "compiles")["ok"] is None  # a missing package is not judged


@pytest.mark.parametrize("error", ["PermissionError: [Errno 13] Permission denied: 'data.csv'",
                                   "ConnectionRefusedError: [Errno 111] Connection refused",
                                   "urllib.error.URLError: <urlopen error [Errno 101] Network is unreachable>"])
def test_an_import_that_the_sandbox_stopped_is_not_held_against_the_file(error):
    trace = f"Traceback (most recent call last):\n  File \"a.py\", line 3, in <module>\n    load()\n{error}"
    boxed = with_note(trace, Isolation(True, "bwrap"))
    open_ = with_note(trace, Isolation(False, "none", "the sandbox is off in Settings", "off"))
    assert run_outcome("a.py", ["a.py"], boxed, False, "compiles")["ok"] is None  # no network or files here: not judged
    assert run_outcome("a.py", ["a.py"], open_, False, "compiles")["ok"] is False  # it ran freely: a real failure
    assert was_isolated(boxed) and not was_isolated(open_) and not was_isolated(trace)


# ---------------------------------------------------------------- the three settings
def test_the_mode_is_one_of_auto_off_required():
    assert MODES == ("auto", "off", "required") and Sandbox().mode == "auto"
    with pytest.raises(ValueError):
        Sandbox("sometimes")
    box = Sandbox()
    with pytest.raises(ValueError):
        box.mode = "maybe"
    assert box.mode == "auto"


@pytest.mark.parametrize(("platform", "code"), [("win32", "windows"), ("freebsd14", "unsupported_os")])
def test_other_systems_run_the_code_as_before_and_say_why(platform, code):
    box = Sandbox("auto", platform=platform)
    found = box.available()
    assert not found.isolated and found.code == code and found.reason and found.backend == "none"
    with box.wrapped(["prog", "arg"], cwd="/w", writable=["/w"]) as run:
        assert run.argv == ["prog", "arg"] and run.env == {} and run.new_session and not run.isolation.isolated
    assert box.review() is None


def test_off_never_wraps_even_where_a_sandbox_exists_and_says_so(tmp_path):
    box = Sandbox("off", platform="linux", which=lambda name: str(tmp_path / "bwrap"))
    assert box.isolation() == Isolation(False, "none", "the sandbox is off in Settings", "off")
    with box.wrapped(["prog"], cwd="/w", writable=["/w"]) as run:
        assert run.argv == ["prog"] and run.isolation.code == "off"


def test_required_refuses_when_there_is_no_sandbox_and_denies_before_anyone_is_asked():
    box = Sandbox("required", platform="win32")
    review = box.review()
    assert review is not None and review.policy == "deny" and review.code == "sandbox_required"
    assert "required" in review.reason and "Windows" in review.reason and "not run" in review.reason
    with pytest.raises(SandboxRefused) as refused, box.wrapped(["prog"], cwd="/w", writable=["/w"]):
        pytest.fail("the code must not start")
    assert refused.value.isolation.code == "windows" and "required" in str(refused.value)
    box.mode = "auto"
    assert box.review() is None
    box.mode = "off"
    assert box.review() is None


async def test_python_and_run_command_do_not_run_code_when_the_sandbox_is_required_and_missing(tmp_path):
    box = Sandbox("required", platform="win32")
    ws = Workspace(tmp_path)
    marker = tmp_path / "ran"
    py = await PythonRunner(sandbox=box).run({"code": f"open({str(marker)!r}, 'w').write('x')"})
    assert not py.ok and py.content.startswith("error: the sandbox is required") and not marker.exists()
    assert py.data["isolation"]["code"] == "windows"
    cmd = await RunCommand(ws, box).run({"command": f"{sys.executable} -c \"open({str(marker)!r}, 'w')\""})
    assert not cmd.ok and "the sandbox is required" in cmd.content and not marker.exists()


async def test_unavailable_with_auto_runs_the_code_and_the_result_says_it_was_not_isolated(tmp_path):
    ws = Workspace(tmp_path)
    py = await PythonRunner(sandbox=NONE).run({"code": "print(6 * 7)"})
    assert py.ok and py.content.splitlines() == ["42", f"{NOTE}not isolated: Windows has no sandbox SPIKE can use]"]
    assert py.data["isolation"] == {**NONE.available().to_dict()} and py.data["returncode"] == 0
    cmd = await RunCommand(ws, NONE).run({"command": "echo hola"})
    lines = cmd.content.splitlines()
    assert cmd.ok and lines[0] == "exit code 0" and lines[-1].startswith(f"{NOTE}not isolated")
    slow = await PythonRunner(timeout_s=1, sandbox=NONE).run({"code": "while True: pass"})
    assert not slow.ok and "timed out" in slow.content and slow.content.endswith("]") and NOTE in slow.content


# ---------------------------------------------------------------- fake programs
def fake_bwrap(folder: Path, log: Path, exit_code: int = 0, message: str = "") -> Path:
    """A `bwrap` that records its arguments and runs the command after `--`."""
    script = folder / "bwrap"
    body = (f"echo \"$@\" >> '{log}'\nwhile [ \"$1\" != \"--\" ]; do shift; done\nshift\nexec \"$@\"\n" if not exit_code else
            f"echo '{message}' >&2\nexit {exit_code}\n")
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def fake_sandbox_exec(folder: Path, log: Path) -> Path:
    """A `sandbox-exec` that records the profile it was given and runs the command after it."""
    script = folder / "sandbox-exec"
    script.write_text(f"#!/bin/sh\nprintf '%s' \"$2\" > '{log}'\nshift 2\nexec \"$@\"\n", encoding="utf-8")
    script.chmod(0o755)
    return script


@posix
def test_bwrap_on_the_path_is_found_tried_and_used(tmp_path, monkeypatch):
    log = tmp_path / "log"
    fake_bwrap(tmp_path, log)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    box = Sandbox("auto", platform="linux")
    found = box.available()
    assert found == Isolation(True, "bwrap") and box.status() == {
        "mode": "auto", "available": True, "backend": "bwrap", "reason": "", "code": ""}
    assert "--unshare-net" in log.read_text(encoding="utf-8")  # it was tried with the real flags
    with box.wrapped(["prog", "x"], cwd=tmp_path, writable=[tmp_path], readable=["/opt/py"]) as run:
        assert run.argv[0] == str(tmp_path / "bwrap") and run.argv[-2:] == ["prog", "x"]
        assert run.env == {"HOME": "/tmp", "TMPDIR": "/tmp"} and run.isolation.isolated and not run.new_session
        at = run.argv.index("--bind")
        assert run.argv[at:at + 3] == ["--bind", str(tmp_path), str(tmp_path)]
        assert "--unshare-net" in run.argv and "--new-session" in run.argv


@posix
def test_no_bwrap_on_the_path_is_reported_and_looked_for_again_on_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    box = Sandbox("auto", platform="linux")
    assert box.available().code == "no_bwrap" and "not installed" in box.available().reason
    fake_bwrap(tmp_path, tmp_path / "log")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert box.available().code == "no_bwrap"  # kept: it is looked at once
    box.refresh()
    assert box.available().isolated


@posix
def test_a_bwrap_that_cannot_start_counts_as_missing_and_says_what_it_printed(tmp_path):
    fake = fake_bwrap(tmp_path, tmp_path / "log", exit_code=1, message="bwrap: No permissions to create a new namespace")
    box = Sandbox("auto", platform="linux", which=lambda name: str(fake))
    found = box.available()
    assert not found.isolated and found.code == "bwrap_failed" and "No permissions to create a new namespace" in found.reason
    assert box.review() is None and box.isolation() == found
    strict = Sandbox("required", platform="linux", which=lambda name: str(fake))
    assert strict.review() is not None and "No permissions" in strict.review().reason


@posix
async def test_python_runs_through_bwrap_and_does_not_start_a_second_session(tmp_path):
    log = tmp_path / "log"
    fake = fake_bwrap(tmp_path, log)
    box = Sandbox("auto", platform="linux", which=lambda name: str(fake))
    assert box.available().isolated
    log_after_probe = log.read_text(encoding="utf-8")  # the probe has run
    code = "import os; print('hi', os.getpid() == os.getsid(0), os.environ['TMPDIR'])"
    out = await PythonRunner(sandbox=box, readable=[tmp_path]).run({"code": code})
    assert out.ok, out.content
    first, note = out.content.splitlines()
    assert first == "hi False /tmp"  # bwrap makes the session; the tool did not make one before it
    assert note.startswith(f"{NOTE}isolated (bwrap)") and out.data["isolation"]["isolated"] is True
    ran = log.read_text(encoding="utf-8")[len(log_after_probe):].splitlines()[-1]
    assert "--unshare-net" in ran and "--chdir" in ran and ran.rstrip().endswith("main.py")
    assert f"--ro-bind {tmp_path} {tmp_path}" in ran  # the workspace is readable, not writable
    assert f"--bind {tmp_path} " not in ran


@posix
async def test_run_command_goes_through_bwrap_in_the_workspace(tmp_path):
    log = tmp_path / "log"
    fake = fake_bwrap(tmp_path, log)
    ws = Workspace(tmp_path / "proj")
    ws.root.mkdir()
    box = Sandbox("auto", platform="linux", which=lambda name: str(fake))
    out = await RunCommand(ws, box).run({"command": "pwd; echo \"$TMPDIR\""})
    assert out.ok, out.content
    assert strip_note(out.content).splitlines() == ["exit code 0", str(ws.root), "/tmp"]
    assert out.content.splitlines()[-1].startswith(f"{NOTE}isolated (bwrap)")
    ran = log.read_text(encoding="utf-8").splitlines()[-1]
    assert f"--bind {ws.root} {ws.root}" in ran and ran.rstrip().endswith("/bin/sh -c pwd; echo \"$TMPDIR\"")


@posix
async def test_sandbox_exec_on_a_mac_gets_a_profile_and_a_private_temp_folder_that_is_removed(tmp_path):
    profile_log = tmp_path / "profile"
    fake = fake_sandbox_exec(tmp_path, profile_log)
    box = Sandbox("auto", platform="darwin", sandbox_exec=str(fake))
    assert box.available() == Isolation(True, "sandbox-exec")
    code = "import os; print(os.environ['TMPDIR']); print(os.environ['HOME'])"
    out = await PythonRunner(sandbox=box).run({"code": code})
    assert out.ok, out.content
    private, home, note = out.content.splitlines()
    assert private == home and Path(private).name.startswith("spike-sandbox-") and not Path(private).exists()
    assert note.startswith(f"{NOTE}isolated (sandbox-exec)")
    profile = profile_log.read_text(encoding="utf-8")
    assert "(deny default)" in profile and "(deny network*)" in profile
    assert f'(subpath "{os.path.realpath(private)}")' in profile
    assert out.data["isolation"]["backend"] == "sandbox-exec"


@posix
def test_a_missing_sandbox_exec_is_reported(tmp_path):
    box = Sandbox("auto", platform="darwin", sandbox_exec=str(tmp_path / "nope"))
    found = box.available()
    assert not found.isolated and found.code == "no_sandbox_exec" and "nope" in found.reason
    assert Sandbox("auto", platform="darwin").available().code in ("", "no_sandbox_exec", "sandbox_exec_failed")


@posix
async def test_run_command_stops_a_sandbox_that_has_not_made_its_session_yet():
    killed = []

    class Proc:
        returncode, pid = None, 2 ** 22 + 12345  # no such process group

        def kill(self):
            killed.append(True)

    _kill(Proc())
    assert killed == [True]


# ---------------------------------------------------------------- the app: settings, API, permission card
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path, provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    state.sandbox.platform = "win32"  # no sandbox here, whatever machine runs the tests
    state.sandbox.refresh()
    return TestClient(create_app(state)), state


def test_the_setting_defaults_to_auto_is_validated_and_reaches_the_tools(env):
    client, state = env
    assert client.get("/api/settings").json()["sandbox"] == "auto" and state.sandbox.mode == "auto"
    assert client.put("/api/settings", json={"sandbox": "required"}).json()["sandbox"] == "required"
    assert state.sandbox.mode == "required" and state.tools.get("python").sandbox is state.sandbox
    assert client.put("/api/settings", json={"sandbox": "sometimes"}).status_code == 400
    assert state.sandbox.mode == "required" and client.get("/api/settings").json()["sandbox"] == "required"
    status = client.get("/api/sandbox").json()
    assert status == {"mode": "required", "available": False, "backend": "none", "code": "windows",
                      "reason": "Windows has no sandbox SPIKE can use"}
    assert state.tools_for(None).get("data_python").sandbox is state.sandbox
    state2 = AppState(home=state.home, provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    assert state2.sandbox.mode == "required"  # kept between starts


def ask_events(tool_registry, calls, policies=None, headless=False):
    async def go():
        broker = PermissionBroker(policies or {})
        if headless:
            from spike.tools.base import HeadlessBroker
            broker = HeadlessBroker(broker)
        events = []
        provider = ScriptedProvider([calls, text("done")])
        async for ev in run_agent(provider, [Message(role="user", content="x")], tools=tool_registry, broker=broker,
                                  run=AgentRun()):
            events.append(ev)
            if ev["type"] == "permission_request":
                asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], "deny")
        return events

    return asyncio.run(go())


def test_the_permission_card_says_whether_the_run_will_be_isolated(tmp_path):
    registry = default_registry(tmp_path, NONE)
    events = ask_events(registry.subset(["python"]), call("python", {"code": "print(1)"}))
    ask = next(e for e in events if e["type"] == "permission_request")
    assert ask["tool"] == "python" and ask["risk"] == "execute"
    assert ask["isolation"]["isolated"] is False and ask["isolation"]["code"] == "windows"
    assert ask["isolation"]["line"] == "not isolated: Windows has no sandbox SPIKE can use"
    off = Sandbox("off")
    ask = next(e for e in ask_events(default_registry(tmp_path, off).subset(["python"]), call("python", {"code": "1"}))
               if e["type"] == "permission_request")
    assert ask["isolation"]["code"] == "off"
    run = ask_events([RunCommand(Workspace(tmp_path), NONE)], call("run_command", {"command": "ls"}))
    assert next(e for e in run if e["type"] == "permission_request")["isolation"]["isolated"] is False
    other = ask_events(registry.subset(["write_file"]), call("write_file", {"path": "a", "content": "b"}))
    assert "isolation" not in next(e for e in other if e["type"] == "permission_request")


@posix
def test_the_permission_card_says_isolated_when_it_will_be(tmp_path):
    fake = fake_bwrap(tmp_path, tmp_path / "log")
    box = Sandbox("auto", platform="linux", which=lambda name: str(fake))
    events = ask_events(default_registry(tmp_path, box).subset(["python"]), call("python", {"code": "print(1)"}))
    ask = next(e for e in events if e["type"] == "permission_request")
    assert ask["isolation"] == Isolation(True, "bwrap").to_dict()


@pytest.mark.parametrize("headless", [False, True])
def test_required_without_a_sandbox_is_refused_with_no_question_asked(tmp_path, headless):
    box = Sandbox("required", platform="win32")
    ws = Workspace(tmp_path)
    tools = [*default_registry(tmp_path, box).subset(["python"]), RunCommand(ws, box)]
    for name, args in (("python", {"code": "print(1)"}), ("run_command", {"command": "echo hi"})):
        events = ask_events(tools, call(name, args), policies={"python": "allow", "run_command": "allow"}
                            if not headless else {}, headless=headless)
        assert not any(e["type"] == "permission_request" for e in events)
        result = next(e for e in events if e["type"] == "tool_result")
        assert not result["ok"] and "refused: the sandbox is required" in result["content"]
        assert "Windows" in result["content"]


def test_the_terminal_prompt_shows_the_sandbox_line(tmp_path):
    stream = io.StringIO()
    decide, _ = terminal.prompter(terminal.Out(stream), tmp_path, lambda _: "n")
    ev = {"tool": "run_command", "arguments": {"command": "ls"}}
    decide({**ev, "isolation": Isolation(True, "bwrap").to_dict()})
    decide({**ev, "isolation": Isolation(False, "none", "the sandbox is off in Settings", "off").to_dict()})
    decide(ev)
    shown = stream.getvalue()
    assert "sandbox: isolated (bwrap): no network" in shown
    assert "sandbox: not isolated: the sandbox is off in Settings" in shown
    assert shown.count("sandbox:") == 2


# ---------------------------------------------------------------- real isolation (only where the program works)
REAL = Sandbox("required")
REAL_OK = REAL.available().isolated
real = pytest.mark.skipif(not REAL_OK, reason=f"no working sandbox here: {REAL.available().reason}")


@pytest.fixture
def listener():
    """A TCP server on 127.0.0.1 that counts the connections it accepts."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    accepted: list[int] = []

    def accept():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            accepted.append(1)
            conn.close()

    threading.Thread(target=accept, daemon=True).start()
    yield server.getsockname()[1], accepted
    server.close()


CONNECT = """import socket
try:
    socket.create_connection(('127.0.0.1', {port}), timeout=3).close()
    print('connected')
except OSError as e:
    print('blocked', e.__class__.__name__)"""
WRITE = """try:
    open({path!r}, 'w').write('x')
    print('written')
except OSError as e:
    print('refused', e.__class__.__name__)"""


@real
async def test_a_sandboxed_script_cannot_reach_a_server_on_this_computer(listener):
    port, accepted = listener
    free = await PythonRunner(sandbox=Sandbox("off")).run({"code": CONNECT.format(port=port)})
    assert strip_note(free.content) == "connected"  # the server works: only the sandbox can be why the next one fails
    await asyncio.sleep(0.2)
    assert len(accepted) == 1
    boxed = await PythonRunner(sandbox=REAL).run({"code": CONNECT.format(port=port)})
    assert boxed.ok and strip_note(boxed.content).startswith("blocked ") and boxed.data["isolation"]["isolated"] is True
    await asyncio.sleep(0.2)
    assert len(accepted) == 1


@real
async def test_a_sandboxed_script_writes_in_its_folder_and_nowhere_else(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    home = Path("~/spike-sandbox-test.txt").expanduser()
    code = ("print('cwd-write', open('made.txt', 'w').write('x'))\n"
            + WRITE.format(path=str(outside / "evil.txt")) + "\n" + WRITE.format(path=str(home)))
    try:
        out = await PythonRunner(sandbox=REAL).run({"code": code})
        lines = strip_note(out.content).splitlines()
        assert out.ok and lines[0] == "cwd-write 1", out.content
        assert lines[1].startswith("refused") and lines[2].startswith("refused"), out.content
        assert not (outside / "evil.txt").exists() and not home.exists()
    finally:
        home.unlink(missing_ok=True)  # only there if the sandbox let it through


@real
async def test_a_sandboxed_script_reads_the_workspace_but_cannot_change_it(tmp_path):
    (tmp_path / "data.txt").write_text("hola", encoding="utf-8")
    code = f"print(open({str(tmp_path / 'data.txt')!r}).read())\n" + WRITE.format(path=str(tmp_path / "data.txt"))
    out = await PythonRunner(sandbox=REAL, readable=[tmp_path]).run({"code": code})
    assert strip_note(out.content).splitlines()[0] == "hola" and "refused" in out.content
    assert (tmp_path / "data.txt").read_text(encoding="utf-8") == "hola"


@real
async def test_a_sandboxed_command_writes_in_the_workspace_and_nowhere_else(tmp_path, listener):
    ws = Workspace(tmp_path / "proj")
    ws.root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    port, accepted = listener
    py = f'"{sys.executable}"'
    tool = RunCommand(ws, REAL)
    inside = await tool.run({"command": f"{py} -c \"open('made.txt', 'w').write('x')\""})
    assert inside.ok, inside.content
    assert (ws.root / "made.txt").read_text(encoding="utf-8") == "x"
    elsewhere = await tool.run({"command": f"{py} -c \"open({str(outside / 'evil.txt')!r}, 'w')\""})
    assert not elsewhere.ok and not (outside / "evil.txt").exists()
    connect = f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=3)"
    net = await tool.run({"command": f"{py} -c \"{connect}\""})
    assert not net.ok and accepted == []
    assert "isolated (" in net.content.splitlines()[-1]
