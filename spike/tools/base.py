"""Tool interface, registry and permission policy."""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from spike.core.types import ToolSpec

Policy = Literal["allow", "ask", "deny"]
Risk = Literal["safe", "read", "write", "execute", "network"]


@dataclass
class Review:
    """A tool's own say on one call, on top of its policy: `deny` or `ask` (with why), or `allow` for a target
    the user already allowed (a browser domain). `once`: the user decides this call only, never "always".
    `code` names the reason so the app can show it in the user's language."""

    policy: Policy
    reason: str = ""
    once: bool = False
    domain: str | None = None
    code: str = ""


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    private: list[str] = field(default_factory=list)  # parts of `content` that are the user's file contents


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk = "safe"
    default_policy: Policy = "allow"

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    @abstractmethod
    async def run(self, args: dict[str, Any]) -> ToolResult: ...

    def targets(self, args: dict[str, Any]) -> list[Path]:
        """Files this call would change, so a copy can be kept to undo it (write tools override this)."""
        return []

    def review(self, args: dict[str, Any]) -> Review | None:
        """A per-call decision that overrides the tool's policy (the browser's domains and form submissions)."""
        return None


class ToolRegistry:
    """Built-in tools, plus `shared` ones (connector tools) that every specialist gets while they are running."""

    def __init__(self, tools: list[Tool] | None = None, shared: Callable[[], list[Tool]] | None = None):
        self._tools: dict[str, Tool] = {}
        self.shared = shared
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def shared_tools(self) -> list[Tool]:
        return [t for t in (self.shared() if self.shared else []) if t.name not in self._tools]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name) or next((t for t in self.shared_tools() if t.name == name), None)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def subset(self, names: list[str]) -> list[Tool]:
        return [self._tools[n] for n in names if n in self._tools]

    def all(self) -> list[Tool]:
        return [self._tools[n] for n in self.names()] + sorted(self.shared_tools(), key=lambda t: t.name)


@dataclass
class PermissionRequest:
    id: str
    tool: str
    arguments: dict[str, Any]
    risk: str
    future: asyncio.Future[str]
    review: Review | None = None


@dataclass
class Question:
    id: str
    text: str
    options: list[str]
    future: asyncio.Future[str]


QUESTION_TIMEOUT_S = 1800.0  # a question waits longer than an approval: the user may need to look something up


class PermissionBroker:
    """Holds pending 'ask' decisions, and questions a model asked the user (`ask_user`), until the user answers in
    the UI (or a timeout denies them)."""

    interactive = True

    def __init__(self, policies: dict[str, Policy] | None = None, timeout_s: float = 300.0):
        self.policies: dict[str, Policy] = dict(policies or {})
        self.on_domain: Callable[[str, str], None] | None = None  # saves "allow"/"deny" for a browser domain
        self.session_allow: set[str] = set()
        self.pending: dict[str, PermissionRequest] = {}
        self.questions: dict[str, Question] = {}
        self.timeout_s = timeout_s

    def ask(self, text: str, options: list[str]) -> Question:
        q = Question(id=f"ask_{uuid.uuid4().hex[:12]}", text=text, options=options,
                     future=asyncio.get_running_loop().create_future())
        self.questions[q.id] = q
        return q

    async def wait_answer(self, q: Question, timeout_s: float = QUESTION_TIMEOUT_S) -> str | None:
        try:
            return await asyncio.wait_for(asyncio.shield(q.future), timeout=timeout_s)
        except TimeoutError:
            return None
        finally:
            self.questions.pop(q.id, None)

    def answer(self, question_id: str, text: str) -> bool:
        q = self.questions.get(question_id)
        if q is None or q.future.done():
            return False
        q.future.set_result(text)
        return True

    def policy_for(self, tool: Tool) -> Policy:
        if tool.name in self.session_allow:
            return "allow"
        return self.policies.get(tool.name, tool.default_policy)

    def policy_for_call(self, tool: Tool, arguments: dict[str, Any]) -> tuple[Policy, Review | None]:
        """The tool's policy, overridden by its review of this call: a deny always wins, an `ask` from the review
        asks even when the tool is allowed, and an `allow` (an allowed domain) skips the question."""
        base = self.policy_for(tool)
        review = tool.review(arguments)
        if base == "deny" or review is None:
            return base, review
        return review.policy, review

    def open(self, tool: Tool, arguments: dict[str, Any], review: Review | None = None) -> PermissionRequest:
        req = PermissionRequest(
            id=f"perm_{uuid.uuid4().hex[:12]}", tool=tool.name, arguments=arguments, risk=tool.risk,
            future=asyncio.get_running_loop().create_future(), review=review,
        )
        self.pending[req.id] = req
        return req

    async def wait(self, req: PermissionRequest) -> str:
        try:
            return await asyncio.wait_for(asyncio.shield(req.future), timeout=self.timeout_s)
        except TimeoutError:
            return "deny"
        finally:
            self.pending.pop(req.id, None)

    def resolve(self, request_id: str, decision: str) -> bool:
        if decision not in {"allow_once", "allow_always", "deny", "allow_domain", "block_domain"}:
            raise ValueError(f"invalid decision '{decision}'")
        req = self.pending.get(request_id)
        if req is None or req.future.done():
            return False
        review = req.review
        if decision == "allow_always" and review and review.domain:
            decision = "allow_domain"  # "always" for a page means its domain, not every site
        if decision in ("allow_domain", "block_domain"):
            if not (review and review.domain and self.on_domain):
                raise ValueError("this request is not about a domain")
            self.on_domain(review.domain, "allow" if decision == "allow_domain" else "deny")
            decision = "allow_once" if decision == "allow_domain" else "deny"
        if decision == "allow_always" and review and review.once:
            decision = "allow_once"  # submitting a form or sending files is confirmed every time
        if decision == "allow_always":
            self.session_allow.add(req.tool)
        req.future.set_result(decision)
        return True


class HeadlessBroker(PermissionBroker):
    """The app's policies for callers nobody can answer (the /v1 API): an 'ask' tool is refused, never waited on."""

    interactive = False

    def __init__(self, parent: PermissionBroker):
        super().__init__(timeout_s=0)
        self.parent = parent

    def policy_for(self, tool: Tool) -> Policy:
        return self.parent.policy_for(tool)
