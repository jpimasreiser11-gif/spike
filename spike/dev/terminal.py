"""The terminal side of `spike dev`: prints the run as it happens, asks before edits and commands (showing the diff
or the command), and handles the slash commands. Ctrl-C stops the current request; Ctrl-D or /exit leaves."""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from spike.dev.session import DevSession, Event
from spike.store.checkpoints import CheckpointError

HELP = """/undo   put back the files of the latest change (repeat to go further back)
/steps  list the file changes SPIKE made in this folder
/clear  start a new conversation (the changes stay undoable)
/help   this list
/exit   leave (also Ctrl-D); Ctrl-C stops the current request"""
PREVIEW_LINES = 40


class Out:
    """Writes with colour only to a terminal that accepts it (NO_COLOR is respected)."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.colour = stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"

    def __call__(self, text: str = "", end: str = "\n", style: str = "") -> None:
        codes = {"dim": "2", "red": "31", "green": "32", "yellow": "33", "bold": "1"}
        if self.colour and style:
            text = f"\033[{codes[style]}m{text}\033[0m"
        self.stream.write(text + end)
        self.stream.flush()


def _short(value: Any, n: int = 120) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def call_label(name: str, args: dict[str, Any]) -> str:
    for key in ("command", "path", "pattern", "glob", "url", "question", "name", "expression"):
        if args.get(key):
            return f"{name} {_short(args[key])}"
    return name


def preview(ev: Event, root: Path) -> list[str]:
    """What an edit or a command would do, for the approval prompt."""
    args, tool = ev.get("arguments") or {}, ev["tool"]
    if tool == "run_command":
        return [f"$ {args.get('command', '')}", "(what a command changes cannot be undone with /undo)"]
    if tool in ("edit_file", "write_file"):
        path = str(args.get("path", ""))
        target = (root / path).resolve()
        try:
            text = target.read_text(encoding="utf-8") if target.is_file() else None
        except (OSError, UnicodeDecodeError):
            text = None
        current = text.splitlines() if text is not None else None
        if tool == "edit_file":
            before, after = str(args.get("old", "")), str(args.get("new", ""))
            if text is not None and before and before in text:  # the whole file, so the diff has context and lines
                old = current or []
                new = (text.replace(before, after) if args.get("replace_all") else
                       text.replace(before, after, 1)).splitlines()
            else:
                old, new = before.splitlines(), after.splitlines()
        else:
            old, new = current or [], str(args.get("content", "")).splitlines()
            if current is None:
                lines = [f"new file {path} ({len(new)} lines)", *(f"+{line}" for line in new)]
                return lines[:PREVIEW_LINES] + ([f"… {len(lines) - PREVIEW_LINES} more lines"]
                                                if len(lines) > PREVIEW_LINES else [])
        diff = list(difflib.unified_diff(old, new, f"a/{path}", f"b/{path}", n=2, lineterm=""))
        return diff[:PREVIEW_LINES] + ([f"… {len(diff) - PREVIEW_LINES} more lines"]
                                       if len(diff) > PREVIEW_LINES else []) or [f"{path}: no change"]
    return [_short(json.dumps(args, ensure_ascii=False), 400)]


def prompter(out: Out, root: Path, read: Callable[[str], str]) -> tuple[Callable[[Event], str],
                                                                      Callable[[Event], str | None]]:
    """The `decide` and `answer` of an interactive session."""

    def decide(ev: Event) -> str:
        out()
        out(f"SPIKE wants to use {ev['tool']}" + (f": {ev['reason']}" if ev.get("reason") else ""), style="bold")
        for line in preview(ev, root):
            style = ("green" if line.startswith("+") and not line.startswith("+++") else
                     "red" if line.startswith("-") and not line.startswith("---") else "dim" if line.startswith("(") else "")
            out("  " + line, style=style)
        isolation = ev.get("isolation")
        if isolation:  # tools that run code: whether this run is isolated from the computer
            out("  sandbox: " + isolation["line"], style="green" if isolation["isolated"] else "yellow")
        choices = "[y] yes  [n] no" if ev.get("once") else "[y] yes  [a] always this session  [n] no"
        while True:
            reply = read(f"Allow? {choices} › ").strip().lower()
            if reply in ("y", "yes", "s", "si", "sí"):
                return "allow_once"
            if reply in ("a", "always", "siempre") and not ev.get("once"):
                return "allow_always"
            if reply in ("n", "no", ""):
                return "deny"

    def answer(ev: Event) -> str | None:
        out()
        out(f"SPIKE asks: {ev['question']}", style="bold")
        for i, option in enumerate(ev.get("options") or [], 1):
            out(f"  {i}. {option}")
        reply = read("› ").strip()
        options = ev.get("options") or []
        if reply.isdigit() and 1 <= int(reply) <= len(options):
            return options[int(reply) - 1]
        return reply or None

    return decide, answer


def headless(out: Out) -> tuple[Callable[[Event], str], Callable[[Event], str | None]]:
    """Nobody at the keyboard: asks are refused, questions get no answer."""

    def decide(ev: Event) -> str:
        out(f"[refused {ev['tool']}: it needs your approval; run `spike dev` interactively, or --accept-edits for "
            "edits]", style="yellow")
        return "deny"

    return decide, lambda ev: None


class Renderer:
    def __init__(self, out: Out):
        self.out = out
        self.calls: dict[str, tuple[str, dict[str, Any]]] = {}
        self.mid_line = False

    def _line(self, text: str, style: str = "") -> None:
        if self.mid_line:
            self.out()
            self.mid_line = False
        self.out(text, style=style)

    def __call__(self, ev: Event) -> None:
        kind = ev["type"]
        if kind == "delta" and "subtask" not in ev:
            self.out(ev["text"], end="")
            self.mid_line = not ev["text"].endswith("\n")
        elif kind == "skill":
            self._line(f"[skill: {', '.join(ev['names'])}]", "dim")
        elif kind == "subtask_start":
            self._line(f"[{ev.get('name', ev.get('specialist', ''))}: {_short(ev.get('instruction', ''), 80)}]", "dim")
        elif kind == "tool_call":
            self.calls[ev["id"]] = (ev["name"], ev.get("arguments") or {})
            self._line(f"→ {call_label(ev['name'], ev.get('arguments') or {})}", "dim")
        elif kind == "tool_result":
            lines = (ev.get("content") or "").splitlines() or [""]
            self._line(f"  {'✓' if ev['ok'] else '✗'} {_short(lines[0], 160)}", "green" if ev["ok"] else "red")
            if ev["name"] == "run_command" and len(lines) > 1:
                tail = lines[1:][-6:]
                for line in tail:
                    self.out(f"    {_short(line, 200)}", style="dim")
        elif kind == "permission_resolved" and ev["decision"] == "deny":
            self._line("  (not allowed)", "yellow")
        elif kind == "context_trimmed":
            self._line(f"[{ev['dropped']} older messages left out to fit the context]", "dim")
        elif kind == "error":
            self._line(f"error: {ev['message']}", "red")
        elif kind == "done":
            if self.mid_line:
                self.out()
                self.mid_line = False
            self.out(f"[{ev['elapsed_s']:.1f} s]", style="dim")


def steps_text(session: DevSession) -> list[str]:
    rows = []
    for i, cp in enumerate(session.changes(), 1):
        files = ", ".join(session.relative(f["path"]) for f in cp["files"])
        rows.append(f"{i:>3}. {cp['tool']:<11} {files}{'  (undone)' if cp['undone'] else ''}")
    return rows or ["no file changes yet"]


def undo(session: DevSession, out: Out, read: Callable[[str], str] | None) -> None:
    try:
        cp = session.undo_last()
    except CheckpointError as exc:
        if exc.status != 409:
            out(str(exc), style="yellow")
            return
        out("These files changed after that step:", style="yellow")
        for path in exc.changed:
            out(f"  {session.relative(path)}")
        if read is None or read("Put them back anyway and lose those later changes? [y/N] › ").strip().lower() != "y":
            out("Nothing changed.")
            return
        cp = session.undo_last(force=True)
    out("Put back: " + ", ".join(session.relative(f["path"]) for f in cp["files"]), style="green")


def run_turn(loop: asyncio.AbstractEventLoop, session: DevSession, text: str, render: Callable[[Event], None],
             out: Out) -> bool:
    """One request; False when it failed or was stopped (Ctrl-C)."""

    async def consume() -> bool:
        ok = True
        async for ev in session.turn(text):
            render(ev)
            if ev["type"] == "error" or (ev["type"] == "done" and ev.get("error")):
                ok = False
        return ok

    task = loop.create_task(consume())
    try:
        return loop.run_until_complete(task)
    except (KeyboardInterrupt, SystemExit) as exc:  # Ctrl-C, or the terminal closed: stop the request cleanly
        task.cancel()
        with contextlib.suppress(BaseException):
            loop.run_until_complete(task)
        if isinstance(exc, SystemExit):
            raise
        out()
        out("[stopped]", style="yellow")
        return False


def repl(loop: asyncio.AbstractEventLoop, session: DevSession, out: Out, read: Callable[[str], str]) -> int:
    render = Renderer(out)
    while True:
        try:
            line = read("› ").strip()
        except EOFError:
            out()
            return 0
        except KeyboardInterrupt:
            out()
            continue
        if not line:
            continue
        if line.startswith("/"):
            command = line.split()[0].lower()
            if command in ("/exit", "/quit"):
                return 0
            if command == "/help":
                out(HELP)
            elif command == "/steps":
                for row in steps_text(session):
                    out(row)
            elif command == "/undo":
                undo(session, out, read)
            elif command == "/clear":
                session.clear()
                out("New conversation. /undo still reaches the earlier changes.", style="dim")
            else:
                out(f"unknown command {command}; /help lists them", style="yellow")
            continue
        run_turn(loop, session, line, render, out)


def main(session: DevSession, loop: asyncio.AbstractEventLoop, prompt: str | None = None) -> int:
    """`spike dev`: an interactive session, or one request with `prompt` (-p): the answer on stdout, the rest on
    stderr, and every ask refused."""
    if prompt is not None:
        err = Out(sys.stderr)
        session.decide, session.answer = headless(err)
        answer, trace = Renderer(Out(sys.stdout)), Renderer(err)

        def render(ev: Event) -> None:
            if ev["type"] == "delta":
                answer(ev)
                return
            if ev["type"] == "done" and answer.mid_line:
                answer.out()
            trace(ev)

        return 0 if run_turn(loop, session, prompt, render, err) else 1
    out = Out(sys.stdout)
    tty = sys.stdin.isatty()
    session.decide, session.answer = prompter(out, session.root, input) if tty else headless(out)
    provider, model = session.backend()
    edits = "edits without asking" if session.broker.policies.get("edit_file") == "allow" else "edits ask first"
    out(f"SPIKE dev · {session.root}", style="bold")
    out(f"{session.specialist} on {provider}{f' ({model})' if model else ''} · {edits} · commands ask first · "
        f"sandbox: {session.state.sandbox.isolation(command=True).line()} · /help", style="dim")
    if session.root in (Path.home(), Path(session.root.anchor)):
        out("warning: this is your whole home folder or disk; SPIKE can change anything in it with your OK",
            style="yellow")
    if session.history:
        out(f"[continuing: {len(session.history)} earlier messages]", style="dim")
    return repl(loop, session, out, input if tty else _read_plain)


def _read_plain(prompt: str) -> str:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line
