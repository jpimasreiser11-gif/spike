"""OS-level isolation for the tools that run code (`python`, `data_python`, `run_command`). With the setting `sandbox`
on `auto` (the default) the code a model writes (`python`, `data_python`) is wrapped in the computer's own sandbox
when there is one: `bwrap` (bubblewrap) on Linux, `/usr/bin/sandbox-exec` on macOS. The wrapped program cannot reach
the network, sees only the system, the Python interpreter and the folders it is given, and writes only in its working
folder and a private temporary folder. A shell command (`run_command`, which the user approves word by word) is
wrapped only under `required`: under `auto` it runs as the user's own, and says so, because isolating it would stop
`npm install`, `git pull` and tools installed under the home folder. Windows, or a computer without the program,
runs the code as before and says so (`isolated: false` with the reason); `required` refuses to run code then, `off`
never wraps. SPIKE ships no sandbox of its own: it only builds the command line for the program the user already has
(detected with `shutil.which`, then tried once with a harmless command, so a bwrap that cannot create namespaces here
counts as missing)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.tools.base import Review

MODES = ("auto", "off", "required")
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PROBE_TIMEOUT_S = 10
NOTE = "[sandbox: "  # the last line of a tool result says how the run was isolated

# Linux: what a run sees of the system, read-only. A path that is a symlink on the host (/bin -> usr/bin) is made
# the same symlink inside; /etc is bound file by file (loader cache, user names, time zone, Debian's alternatives).
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32")
ETC_ENTRIES = ("alternatives", "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "passwd", "group", "nsswitch.conf",
               "localtime", "timezone", "os-release", "terminfo", "mime.types")
# macOS: the system and the usual places interpreters and tools live in (not the user's home folder)
MAC_READ = ("/usr", "/bin", "/sbin", "/System", "/Library", "/Applications", "/opt", "/private/etc",
            "/private/var/db/dyld", "/private/var/db/timezone", "/private/var/select")
MAC_DEVICES = ("/dev/null", "/dev/dtracehelper")  # read and write
MAC_RANDOM = ("/dev/random", "/dev/urandom", "/dev/zero")  # read only


@dataclass(frozen=True)
class Isolation:
    """How one run is (or is not) isolated. `reason` is English; `code` names it so the app can translate it."""

    isolated: bool
    backend: str = "none"  # bwrap | sandbox-exec | none
    reason: str = ""  # why not isolated
    code: str = ""  # off | approved_command | windows | unsupported_os | no_bwrap | bwrap_failed | no_sandbox_exec |
    # sandbox_exec_failed

    def line(self) -> str:
        if self.isolated:
            return f"isolated ({self.backend}): no network, writes only in the working folder and a private temp folder"
        return f"not isolated: {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        return {"isolated": self.isolated, "backend": self.backend, "reason": self.reason, "code": self.code,
                "line": self.line()}


class SandboxRefused(RuntimeError):
    """The setting is `required` and this computer has no working sandbox: the code is not run."""

    def __init__(self, isolation: Isolation):
        super().__init__(refusal(isolation))
        self.isolation = isolation


def refusal(iso: Isolation) -> str:
    return (f"the sandbox is required (Settings → Tools) but there is none to use here: {iso.reason}. "
            "The code was not run.")


def with_note(content: str, iso: Isolation) -> str:
    """A tool's output followed by one line that says whether the run was isolated."""
    return f"{content}\n{NOTE}{iso.line()}]"


def was_isolated(content: str) -> bool:
    """Whether a tool result's last line says the run was isolated."""
    return content.rpartition("\n")[2].startswith(f"{NOTE}isolated (")


def strip_note(content: str) -> str:
    """The output without `with_note`'s last line (for code that parses what a program printed)."""
    head, sep, last = content.rpartition("\n")
    return head if sep and last.startswith(NOTE) and last.endswith("]") else content


# --------------------------------------------------------------------------- command lines (pure)
def sbpl_quote(path: str) -> str:
    """A path as a quoted string of a macOS sandbox profile."""
    if any(ord(c) < 32 for c in path):
        raise ValueError("a path with a control character cannot be used in a sandbox profile")
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rules(kind: str, paths: Sequence[str]) -> str:
    return " ".join(f"({kind} {sbpl_quote(p)})" for p in dict.fromkeys(paths))


def seatbelt_profile(*, readable: Sequence[str], writable: Sequence[str]) -> str:
    """A macOS sandbox profile (SBPL) that denies everything and then allows: starting programs, reading the
    system and the `readable` folders, reading and writing the `writable` ones and a few devices. Names and sizes of
    other files can be seen (`file-read-metadata`, which paths need to be looked up) but not their contents. The
    network is denied. Paths must be real paths (symlinks resolved): the profile matches those."""
    return "\n".join([
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal (target self))",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        f"(allow file-read* {_rules('subpath', [*MAC_READ, *readable, *writable])} {_rules('literal', MAC_RANDOM)})",
        f"(allow file-read* file-write* {_rules('literal', MAC_DEVICES)})",
        f"(allow file-write* {_rules('subpath', writable)})",
        "(deny network*)",
    ])


def bwrap_argv(argv: Sequence[str], *, binary: str, system: Sequence[tuple[str, str | None]], etc: Sequence[str],
               readable: Sequence[str], writable: Sequence[str], cwd: str) -> list[str]:
    """`argv` inside bubblewrap: no network, own process and IPC namespaces, no capabilities, a new terminal
    session, dies with its parent. Inside: a fresh /proc, /dev and /tmp; the `system` folders read-only (`(path, link)`:
    a symlink on the host stays a symlink); the `etc` files read-only; then the `writable` folders read-write and
    the `readable` ones read-only, so a read-only folder inside a writable one stays read-only."""
    out = [binary, "--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid", "--unshare-ipc",
           "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path, link in system:
        out += ["--symlink", link, path] if link else ["--ro-bind", path, path]
    for name in etc:
        out += ["--ro-bind-try", f"/etc/{name}", f"/etc/{name}"]
    for path in dict.fromkeys(writable):
        out += ["--bind", path, path]
    for path in dict.fromkeys(readable):
        out += ["--ro-bind", path, path]
    return [*out, "--chdir", cwd, "--", *argv]


def system_layout(root: str = "/") -> tuple[list[tuple[str, str | None]], list[str]]:
    """(system folders, /etc entries) that exist on this computer, as `bwrap_argv` takes them."""
    system: list[tuple[str, str | None]] = []
    for path in SYSTEM_DIRS:
        full = os.path.join(root, path.lstrip("/"))
        if os.path.islink(full):
            system.append((path, os.readlink(full)))
        elif os.path.isdir(full):
            system.append((path, None))
    return system, [e for e in ETC_ENTRIES if os.path.lexists(os.path.join(root, "etc", e))]


def interpreter_dirs() -> list[str]:
    """The folders Python needs to start (its prefixes, the virtual environment's and the real interpreter's)."""
    found: list[str] = []
    real = os.path.realpath(sys.executable)
    for path in (sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix,
                 os.path.dirname(os.path.dirname(real))):
        path = os.path.abspath(path)
        if path != os.path.abspath(os.sep) and os.path.isdir(path) and path not in found:
            found.append(path)
    return found


# --------------------------------------------------------------------------- the sandbox of one app
@dataclass
class Wrapped:
    """What to run: `argv` (wrapped when `isolation.isolated`), the environment variables to add, and whether the
    caller still has to start its own terminal session (bubblewrap does it itself, and cannot do it twice)."""

    argv: list[str]
    env: dict[str, str]
    isolation: Isolation
    new_session: bool = True


class Sandbox:
    """The `sandbox` setting (`mode`) plus what this computer offers. Detection runs once and is kept; `platform`,
    `which`, `sandbox_exec` and `system_root` can be replaced (tests use fake binaries and other platforms)."""

    def __init__(self, mode: str = "auto", *, platform: str | None = None,
                 which: Callable[[str], str | None] = shutil.which, sandbox_exec: str = SANDBOX_EXEC,
                 system_root: str = "/"):
        self.mode = mode
        self.platform = platform or sys.platform
        self.which, self.sandbox_exec, self.system_root = which, sandbox_exec, system_root
        self._found: Isolation | None = None
        self._binary = ""

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in MODES:
            raise ValueError(f"sandbox must be one of {', '.join(MODES)}")
        self._mode = value

    # ------------------------------------------------------------------ what the computer offers
    def refresh(self) -> None:
        """Look again (a program was installed since the first look)."""
        self._found = None

    def available(self) -> Isolation:
        """Whether this computer has a working sandbox, whatever the setting says."""
        if self._found is None:
            self._found = self._detect()
        return self._found

    def _detect(self) -> Isolation:
        if self.platform == "darwin":
            name, binary, missing = "sandbox-exec", self.sandbox_exec, "no_sandbox_exec"
            if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
                return Isolation(False, "none", f"{binary} was not found", missing)
        elif self.platform.startswith("linux"):
            name, missing = "bwrap", "no_bwrap"
            binary = self.which("bwrap") or ""
            if not binary:
                return Isolation(False, "none", "bubblewrap (bwrap) is not installed", missing)
        elif self.platform in ("win32", "cygwin"):
            return Isolation(False, "none", "Windows has no sandbox SPIKE can use", "windows")
        else:
            return Isolation(False, "none", f"no sandbox is known for {self.platform}", "unsupported_os")
        problem = self._probe(binary)
        if problem:
            code = "bwrap_failed" if name == "bwrap" else "sandbox_exec_failed"
            return Isolation(False, "none", f"{name} does not work here: {problem}", code)
        self._binary = binary
        return Isolation(True, name)

    def _probe(self, binary: str) -> str:
        """"" when `binary` runs a harmless Python start in a sandbox like the real ones; else what went wrong."""
        try:
            with tempfile.TemporaryDirectory(prefix="spike-probe-") as tmp, self._command(
                    binary, [sys.executable, "-I", "-c", "pass"], tmp, [tmp], []) as box:
                done = subprocess.run(box.argv, cwd=tmp, env={**os.environ, **box.env}, capture_output=True,
                                      stdin=subprocess.DEVNULL, timeout=PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{exc.__class__.__name__}: {exc}"
        if done.returncode == 0:
            return ""
        message = done.stderr.decode("utf-8", "replace").strip().splitlines()
        return (message[-1] if message else f"exit code {done.returncode}")[:200]

    # ------------------------------------------------------------------ what a run gets
    def isolation(self, command: bool = False) -> Isolation:
        """How a run would be isolated now, with the setting applied. `command`: a shell command the user approves
        as written (`run_command`), which only `required` isolates."""
        if self.mode == "off":
            return Isolation(False, "none", "the sandbox is off in Settings", "off")
        if command and self.mode == "auto":
            return Isolation(False, "none", "approved commands run outside the sandbox in auto mode", "approved_command")
        return self.available()

    def status(self, refresh: bool = False) -> dict[str, Any]:
        """The setting and what the computer offers (`refresh`: look again first, in case a program was installed)."""
        if refresh:
            self.refresh()
        found = self.available()
        return {"mode": self.mode, "available": found.isolated, "backend": found.backend, "reason": found.reason,
                "code": found.code}

    def review(self) -> Review | None:
        """A deny for the permission check when the setting is `required` and there is no sandbox: the user is not
        asked to approve code that will not run."""
        if self.mode != "required" or self.available().isolated:
            return None
        return Review("deny", refusal(self.available()), code="sandbox_required")

    @contextmanager
    def wrapped(self, argv: Sequence[str], *, cwd: str | Path, writable: Sequence[str | Path],
                readable: Sequence[str | Path] = (), command: bool = False) -> Iterator[Wrapped]:
        """`argv` ready to start: wrapped in the sandbox when there is one and the setting allows it (`command`: a
        shell command, see `isolation`). `writable` folders can be written (the working folder), `readable` ones only
        read. Raises `SandboxRefused` when the setting is `required` and there is none. A private temporary folder
        that macOS needs is removed on exit."""
        iso = self.isolation(command)
        if self.mode == "required" and not iso.isolated:
            raise SandboxRefused(iso)
        if not iso.isolated:
            yield Wrapped(list(argv), {}, iso)
            return
        with self._command(self._binary, argv, cwd, writable, readable) as box:
            yield box

    @contextmanager
    def _command(self, binary: str, argv: Sequence[str], cwd: str | Path, writable: Sequence[str | Path],
                 readable: Sequence[str | Path]) -> Iterator[Wrapped]:
        write = [os.path.abspath(p) for p in writable]
        read = [*interpreter_dirs(), *(p for p in (os.path.abspath(p) for p in readable) if os.path.exists(p))]
        if self.platform == "darwin":
            private = os.path.realpath(tempfile.mkdtemp(prefix="spike-sandbox-"))
            try:
                profile = seatbelt_profile(readable=[os.path.realpath(p) for p in read],
                                           writable=[*(os.path.realpath(p) for p in write), private])
                yield Wrapped([binary, "-p", profile, *argv], {"HOME": private, "TMPDIR": private},
                              Isolation(True, "sandbox-exec"))
            finally:
                shutil.rmtree(private, ignore_errors=True)
            return
        system, etc = system_layout(self.system_root)
        yield Wrapped(bwrap_argv(argv, binary=binary, system=system, etc=etc, readable=read, writable=write,
                                 cwd=os.path.abspath(cwd)), {"HOME": "/tmp", "TMPDIR": "/tmp"},
                      Isolation(True, "bwrap"), new_session=False)


_DEFAULT: Sandbox | None = None


def default_sandbox() -> Sandbox:
    """The sandbox (setting `auto`) of a tool that was not given one."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Sandbox()
    return _DEFAULT
