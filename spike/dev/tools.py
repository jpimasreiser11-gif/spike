"""The tools `spike dev` adds to SPIKE's file tools: edit a file in place, search the folder, find files and run a
command. All of them stay inside the folder `spike dev` was started on; editing keeps a copy first (undo), a
command asks every time unless the user allowed it for the session, and what a command changes cannot be undone."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any

from spike.tools.base import Review, Tool, ToolResult
from spike.tools.builtin import Workspace
from spike.tools.sandbox import Sandbox, SandboxRefused, default_sandbox, with_note

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", "dist", "build", ".next", ".tox", "target"}
MAX_MATCHES = 200
MAX_OUTPUT = 30_000
MAX_FILE = 2 * 1024 * 1024  # bigger files are not searched
RUNNING: set[asyncio.subprocess.Process] = set()  # commands still running; stopped when `spike dev` exits


def walk(root: Path) -> list[Path]:
    """Files under root, skipping version control, dependencies and caches."""
    out: list[Path] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        out += [Path(folder) / f for f in sorted(files)]
    return out


class EditFile(Tool):
    name = "edit_file"
    description = ("Replace an exact piece of text in a workspace file. `old` must appear exactly once (include enough "
                   "surrounding lines to make it unique) unless `replace_all` is true. Read the file first.")
    parameters = {"type": "object", "properties": {
        "path": {"type": "string"}, "old": {"type": "string", "description": "the exact text to replace"},
        "new": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["path", "old", "new"]}
    risk = "write"
    default_policy = "ask"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def targets(self, args: dict[str, Any]) -> list[Path]:
        try:
            return [self.workspace.resolve(str(args["path"]))]
        except (PermissionError, KeyError):
            return []

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = self.workspace.resolve(str(args["path"]))
            text = path.read_text(encoding="utf-8")
        except (PermissionError, FileNotFoundError, IsADirectoryError, KeyError, UnicodeDecodeError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        old, new = str(args.get("old", "")), str(args.get("new", ""))
        if not old:
            return ToolResult(ok=False, content="error: 'old' is empty; use write_file to create a file")
        count = text.count(old)
        if count == 0:
            return ToolResult(ok=False, content="error: 'old' was not found; read the file and copy the text exactly")
        if count > 1 and not args.get("replace_all"):
            return ToolResult(ok=False, content=f"error: 'old' appears {count} times; add surrounding lines to make it "
                                                "unique, or set replace_all")
        path.write_text(text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1),
                        encoding="utf-8")
        rel = path.relative_to(self.workspace.root).as_posix()
        return ToolResult(ok=True, content=f"edited {rel} ({count if args.get('replace_all') else 1} change"
                                           f"{'s' if args.get('replace_all') and count > 1 else ''})",
                          data={"file": rel})


class SearchFiles(Tool):
    name = "search"
    description = ("Search the workspace's text files with a regular expression (Python syntax). Returns path:line: "
                   "text for each match; `glob` limits the files (e.g. *.py).")
    parameters = {"type": "object", "properties": {
        "pattern": {"type": "string"}, "glob": {"type": "string"}, "ignore_case": {"type": "boolean"}},
        "required": ["pattern"]}
    risk = "read"
    default_policy = "allow"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            regex = re.compile(str(args.get("pattern", "")), re.IGNORECASE if args.get("ignore_case") else 0)
        except re.error as exc:
            return ToolResult(ok=False, content=f"error: invalid pattern: {exc}")
        pattern = str(args.get("glob") or "*")
        root = self.workspace.root
        hits: list[str] = []
        for path in walk(root):
            rel = path.relative_to(root).as_posix()
            if not (fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern)):
                continue
            try:
                if path.stat().st_size > MAX_FILE:
                    continue
                with path.open(encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if regex.search(line):
                            hits.append(f"{rel}:{n}: {line.rstrip()[:300]}")
                            if len(hits) >= MAX_MATCHES:
                                break
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable
            if len(hits) >= MAX_MATCHES:
                hits.append(f"[stopped at {MAX_MATCHES} matches; narrow the pattern or the glob]")
                break
        content = "\n".join(hits) or "no matches"
        return ToolResult(ok=True, content=content, private=[content] if hits else [])


class FindFiles(Tool):
    name = "find_files"
    description = "List workspace files whose path matches a glob (e.g. **/*.py, src/*.ts), skipping dependencies."
    parameters = {"type": "object", "properties": {"glob": {"type": "string"}}, "required": ["glob"]}
    risk = "read"
    default_policy = "allow"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        pattern = str(args.get("glob") or "*")
        root = self.workspace.root
        found = [p.relative_to(root).as_posix() for p in walk(root)]
        bare = pattern.removeprefix("**/")
        matches = [r for r in found if fnmatch.fnmatch(r, pattern) or fnmatch.fnmatch(r.rsplit("/", 1)[-1], bare)]
        more = len(matches) - 500
        return ToolResult(ok=True, content="\n".join(matches[:500]) + (f"\n[{more} more]" if more > 0 else "")
                          if matches else "no files")


class RunCommand(Tool):
    name = "run_command"
    description = ("Run a shell command in the workspace folder (tests, builds, git status…) and return its output and "
                   "exit code. The user approves each command; files a command changes cannot be undone. Where the "
                   "computer has a sandbox (bubblewrap on Linux, sandbox-exec on macOS) the command has no network "
                   "and writes only in the workspace; the last line of the result says whether it was isolated.")
    parameters = {"type": "object", "properties": {
        "command": {"type": "string"}, "timeout_s": {"type": "integer", "description": "default 120, at most 600"}},
        "required": ["command"]}
    risk = "execute"
    default_policy = "ask"

    def __init__(self, workspace: Workspace, sandbox: Sandbox | None = None):
        self.workspace = workspace
        self.sandbox = sandbox or default_sandbox()

    def review(self, args: dict[str, Any]) -> Review | None:
        return self.sandbox.review()  # `required` and no sandbox: refused before anyone is asked

    def isolation(self, args: dict[str, Any]) -> dict[str, Any] | None:
        return self.sandbox.isolation().to_dict()

    async def run(self, args: dict[str, Any]) -> ToolResult:
        command = str(args.get("command") or "").strip()
        if not command:
            return ToolResult(ok=False, content="error: 'command' is empty")
        timeout = max(1, min(int(args.get("timeout_s") or 120), 600))
        pipes = {"cwd": self.workspace.root, "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT,
                 "stdin": asyncio.subprocess.DEVNULL}
        try:
            with self.sandbox.wrapped(["/bin/sh", "-c", command], cwd=self.workspace.root,
                                      writable=[self.workspace.root]) as box:
                if os.name == "nt":  # cmd.exe, quoted the way it expects (a list would escape inner quotes as \")
                    proc = await asyncio.create_subprocess_shell(command, **pipes)
                else:
                    proc = await asyncio.create_subprocess_exec(
                        *box.argv, start_new_session=box.new_session, **pipes,
                        **({"env": {**os.environ, **box.env}} if box.isolation.isolated else {}))
                RUNNING.add(proc)
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout)
                except TimeoutError:
                    _kill(proc)
                    await proc.wait()
                    return ToolResult(ok=False, content=with_note(f"error: timed out after {timeout} s", box.isolation),
                                      data={"isolation": box.isolation.to_dict()})
                except BaseException:  # the request was stopped (Ctrl-C): the command stops with it
                    _kill(proc)
                    raise
                finally:
                    RUNNING.discard(proc)
        except SandboxRefused as exc:
            return ToolResult(ok=False, content=f"error: {exc}", data={"isolation": exc.isolation.to_dict()})
        text = out.decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT // 3] + f"\n[… {len(text) - MAX_OUTPUT} chars cut …]\n" + text[-2 * MAX_OUTPUT // 3:]
        return ToolResult(ok=proc.returncode == 0, content=with_note(f"exit code {proc.returncode}\n{text}".rstrip(),
                                                                       box.isolation),
                          private=[text] if text else [], data={"isolation": box.isolation.to_dict()})


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # the whole process group: test runners start children
            except ProcessLookupError:  # a sandbox that has not made its session yet: kill it (its child dies with it)
                proc.kill()
            return
        try:  # the same on Windows: cmd.exe and everything it started
            tree = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            tree = None
        if tree is None or tree.returncode:
            proc.kill()  # at least the shell
    except OSError:  # already gone
        pass


def stop_commands() -> None:
    for proc in list(RUNNING):
        _kill(proc)


def dev_tools(workspace: Workspace, sandbox: Sandbox | None = None) -> list[Tool]:
    return [EditFile(workspace), SearchFiles(workspace), FindFiles(workspace), RunCommand(workspace, sandbox)]
