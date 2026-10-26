"""A `spike dev` session: SPIKE's agent loop working on one folder from the terminal. The model reads, searches,
edits files and runs commands there; every edit keeps a copy first (`/undo`), every ask goes to the user through
`decide`, and the conversation is kept so `--continue` picks it up again."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from spike.core.types import Message
from spike.dev.tools import dev_tools
from spike.orchestrator.orchestrator import Orchestrator, OrchestratorOptions
from spike.server.state import AppState
from spike.store.checkpoints import CheckpointError, Checkpoints, RunCheckpoints
from spike.store.db import Store
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace, default_registry

Event = dict[str, Any]
MAX_STEPS = 30  # model calls per request: reading, editing and testing take more steps than a chat answer
PROJECT_FILES = ("SPIKE.md", "AGENTS.md")  # the folder's own instructions, the first one found
MAX_PROJECT_CHARS = 8000
DECISIONS = {"allow_once", "allow_always", "deny"}
EDIT_TOOLS = ("write_file", "edit_file")
DEV_INSTRUCTIONS = """You are working as a coding agent in the folder {root}; every path is relative to it.
- Look before you change anything: find_files, search and read_file. Use edit_file to change an existing file and \
write_file only for new files.
- Prove each change: run the project's tests or the command that shows it works with run_command, and report the \
real output. Never say something passes without running it.
- Keep changes small and on the request; do not touch unrelated files or reformat code you did not change.
- If the request is unclear or a step is risky, ask with ask_user before acting.
- When you finish, list the files you changed and what you ran to check them."""


def project_instructions(root: Path) -> str:
    for name in PROJECT_FILES:
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            cut = text[:MAX_PROJECT_CHARS] + ("\n[…cut]" if len(text) > MAX_PROJECT_CHARS else "")
            return f"From {name}:\n{cut}"
    return ""


def no_decision(ev: Event) -> str:
    return "deny"


def no_answer(ev: Event) -> str | None:
    return None


class DevSession:
    """`decide(permission_request) -> allow_once | allow_always | deny` and `answer(question) -> text | None` are
    the user; `None` means nobody can answer and the model is told to go on with its best assumption."""

    def __init__(self, state: AppState, root: Path, *, provider_id: str | None = None, specialist: str = "code",
                 accept_edits: bool = False, resume: bool = False,
                 decide: Callable[[Event], str] = no_decision, answer: Callable[[Event], str | None] = no_answer):
        self.state = state
        self.root = Workspace(root).root
        if not self.root.is_dir():
            raise FileNotFoundError(f"{self.root} is not a folder")
        if specialist != "auto":
            state.catalog.get(specialist)  # KeyError for an unknown specialist
        self.specialist, self.provider_id = specialist, provider_id
        self.decide, self.answer = decide, answer
        home = state.home / "dev"
        self.store = Store(home / "sessions.db")
        self.checkpoints = Checkpoints(self.store, home / "checkpoints")
        policies = dict(state.settings()["tool_policies"])
        if accept_edits:
            policies.update({t: "allow" for t in EDIT_TOOLS})
        self.broker = PermissionBroker(policies, timeout_s=24 * 3600)  # someone is at the terminal: no timeout
        tools = default_registry(self.root, state.sandbox)
        extra = dev_tools(Workspace(self.root), state.sandbox, state.connectors)
        tools.shared = lambda: extra  # every specialist gets them, not only those that list them
        base = state.orchestrator(provider_id)
        self.orchestrator = Orchestrator(state.catalog, base.resolve, tools, self.broker, skills=state.skills)
        self.title = f"dev:{self.root}"
        latest = next((c for c in self.store.list_conversations() if c["title"] == self.title), None) if resume else None
        self.conversation_id = latest["id"] if latest else self._new_conversation()
        self.history = [Message(role=m["role"], content=m["content"],
                                private=[m["content"]] if m["meta"].get("private") else [])
                        for m in self.store.messages(self.conversation_id)
                        if m["role"] in ("user", "assistant") and m["content"]]

    def _new_conversation(self) -> str:
        return self.store.create_conversation(title=self.title, mode=self.specialist,
                                              provider_id=self.provider_id)["id"]

    def backend(self) -> tuple[str, str]:
        """(provider name, model) of the specialist that answers."""
        spec = self.state.catalog.get("core" if self.specialist == "auto" else self.specialist)
        b = self.orchestrator.resolve(spec)
        return b.provider.config.name, b.model or b.provider.config.model or ""

    def options(self) -> OrchestratorOptions:
        s = self.state.settings()
        return OrchestratorOptions(
            mode=self.specialist, custom_instructions=s["custom_instructions"],
            specialist_instructions=s["specialist_instructions"], project_instructions=project_instructions(self.root),
            app_instructions=DEV_INSTRUCTIONS.format(root=self.root), skill_mode=s["skill_mode"],
            disabled_skills=list(s["disabled_skills"]), use_planner=s["use_planner"], parallel=False,
            temperature=s["temperature"], max_tokens=s["max_tokens"], reasoning=s["reasoning"], tools_enabled=True,
            checkpoints=RunCheckpoints(self.checkpoints, self.conversation_id), max_steps=MAX_STEPS)

    async def turn(self, text: str) -> AsyncIterator[Event]:
        """Run one request; asks are settled through `decide` / `answer` before the run goes on."""
        self.store.add_message(self.conversation_id, "user", text)
        parts: list[str] = []
        done: Event | None = None
        try:
            async for ev in self.orchestrator.run(self.history, text, self.options()):
                kind = ev["type"]
                if kind == "permission_request":
                    decision = self.decide(ev)
                    self.broker.resolve(ev["id"], decision if decision in DECISIONS else "deny")
                elif kind == "question":
                    reply = self.answer(ev)
                    self.broker.answer(ev["id"], reply if reply is not None else
                                       "(nobody can answer here; go on with your best assumption and say what you "
                                       "assumed)")
                elif kind == "delta" and "subtask" not in ev:
                    parts.append(ev["text"])
                elif kind == "done":
                    done = ev
                yield ev
        finally:  # a stopped request still keeps what was written, so the next one knows
            answer = done["text"] if done else "".join(parts)
            meta = {"private": bool(done and done["private"]), "specialists": done["specialists"] if done else [],
                    **({"error": done["error"]} if done and done["error"] else {}),
                    **({} if done else {"stopped": True})}
            self.store.add_message(self.conversation_id, "assistant", answer, meta)
            self.history.append(Message(role="user", content=text))
            if answer:
                self.history.append(Message(role="assistant", content=answer,
                                            private=[answer] if meta["private"] else []))

    # ------------------------------------------------------------------ undo
    def changes(self) -> list[dict[str, Any]]:
        """File changes SPIKE made in this folder (this session and earlier ones), oldest first."""
        ids = [c["id"] for c in self.store.list_conversations(limit=100_000) if c["title"] == self.title]
        return sorted((cp for cid in ids for cp in self.store.list_checkpoints(cid)), key=lambda c: c["created"])

    def undo_last(self, force: bool = False) -> dict[str, Any]:
        """Put back the files of the latest change not undone yet; CheckpointError(409) when they changed since."""
        pending = [c for c in self.changes() if not c["undone"]]
        if not pending:
            raise CheckpointError(400, "nothing to undo")
        return self.checkpoints.undo(pending[-1]["id"], force=force)

    def clear(self) -> None:
        """A new conversation on the same folder; `/undo` still reaches the changes made before."""
        self.conversation_id = self._new_conversation()
        self.history = []

    def relative(self, path: str) -> str:
        p = Path(path)
        return p.relative_to(self.root).as_posix() if p.is_relative_to(self.root) else path
