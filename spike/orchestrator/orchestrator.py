"""The SPIKE orchestrator: route -> (plan) -> run specialists -> synthesize, streaming every step."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from spike.agent.loop import AgentRun, Checkpointer, Event, run_agent
from spike.core.types import Message
from spike.memory.service import Recall, memory_section
from spike.orchestrator.planner import Plan, Subtask, make_plan, topological_levels
from spike.orchestrator.router import LexicalRouter, RouteDecision
from spike.providers.base import Provider
from spike.skills.engine import LoadSkill, SkillLibrary, catalog_prompt, skill_prompt
from spike.specialists.catalog import Catalog, Specialist
from spike.tools.base import PermissionBroker, Tool, ToolRegistry


@dataclass
class Backend:
    """Where a specialist runs. `adapter` is None when the backend cannot load the specialist's adapter."""

    provider: Provider
    model: str | None
    adapter: str | None
    context_budget: int = 24_000

    @property
    def profile_only(self) -> bool:
        return self.adapter is None


BackendResolver = Callable[[Specialist], Backend]


@dataclass
class OrchestratorOptions:
    mode: str = "auto"  # "auto" or a specialist id
    custom_instructions: str = ""
    specialist_instructions: dict[str, str] = field(default_factory=dict)
    use_planner: bool = True
    max_subtasks: int = 4
    parallel: bool = False  # run independent subtasks concurrently (sensible for remote APIs only)
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: bool | None = None
    tools_enabled: bool = True
    app_instructions: str = ""  # system prompt of an application calling SPIKE through the /v1 API
    project_instructions: str = ""
    skill_mode: str = "auto"  # auto (router for local models, model's choice for APIs) | router | model | off
    disabled_skills: list[str] = field(default_factory=list)
    memory: Recall | None = None  # rules and notes recalled for this message (Neural Memory)
    checkpoints: Checkpointer | None = None  # copies of files before tools change them (undo), for app chats


SYNTHESIS_INSTRUCTIONS = (
    "You are writing the final answer for the user. Specialist reports are provided below. Merge them into "
    "one coherent, well-structured answer in the user's language. Resolve contradictions explicitly, keep "
    "every important caveat and uncertainty the specialists raised, do not add facts they did not provide "
    "unless you are confident, and do not mention internal subtask ids."
)


class Orchestrator:
    def __init__(self, catalog: Catalog, resolve: BackendResolver, tools: ToolRegistry, broker: PermissionBroker,
                 router: LexicalRouter | None = None, skills: SkillLibrary | None = None):
        self.catalog = catalog
        self.resolve = resolve
        self.tools = tools
        self.broker = broker
        self.router = router or LexicalRouter(catalog)
        self.skills = skills

    # ------------------------------------------------------------------ prompts
    def system_prompt(self, spec: Specialist, opts: OrchestratorOptions, extra: str = "",
                      context_budget: int = 24_000) -> str:
        return self.system_message(spec, opts, extra, context_budget).content

    def system_message(self, spec: Specialist, opts: OrchestratorOptions, extra: str = "",
                       context_budget: int = 24_000) -> Message:
        """The system message; its `private` parts are the passages of the user's files that memory recalled."""
        parts = [spec.system_prompt]
        files: list[str] = []
        if opts.custom_instructions.strip():
            parts.append("# Instructions from the user (always follow them)\n" + opts.custom_instructions.strip())
        if opts.project_instructions.strip():
            parts.append("# Project instructions\n" + opts.project_instructions.strip())
        if opts.memory is not None:
            section, files = memory_section(opts.memory, max(200, min(1500, context_budget // 6)))
            if section:
                parts.append(section)
        if opts.specialist_instructions.get(spec.id, "").strip():
            parts.append(f"# Instructions for {spec.name}\n" + opts.specialist_instructions[spec.id].strip())
        if opts.app_instructions.strip():
            parts.append("# Instructions from the application calling SPIKE\n" + opts.app_instructions.strip())
        if extra:
            parts.append(extra)
        return Message(role="system", content="\n\n".join(parts), private=files)

    def _tools_for(self, spec: Specialist, opts: OrchestratorOptions):
        return self.tools.subset(spec.tools) + self.tools.shared_tools() if opts.tools_enabled else []

    def _skills_for(self, spec: Specialist, backend: Backend, text: str,
                    opts: OrchestratorOptions) -> tuple[str, list[Tool], Event | None]:
        """(system prompt section, extra tools, event) for the skills of this run."""
        if self.skills is None or opts.skill_mode == "off":
            return "", [], None
        mode = opts.skill_mode
        if mode == "auto":
            mode = "router" if backend.provider.config.local else "model"
        if mode == "model" and not opts.tools_enabled:
            mode = "router"
        disabled = set(opts.disabled_skills)
        if mode == "router":
            picked = self.skills.select(text, spec.id, disabled)
            if not picked:
                return "", [], None
            budget = max(256, min(3000, backend.context_budget // 4))
            return ("\n\n".join(skill_prompt(s, budget) for s in picked), [],
                    {"type": "skill", "names": [s.name for s in picked], "mode": "router", "specialist": spec.id})
        available = self.skills.available(spec.id, disabled)
        if not available:
            return "", [], None
        return catalog_prompt(available), [LoadSkill(available)], None

    def _route_event(self, decision: RouteDecision, specs: list[Specialist]) -> Event:
        return {
            "type": "route",
            "mode": decision.mode,
            "method": decision.method,
            "confidence": decision.confidence,
            "scores": decision.scores,
            "specialists": [self._spec_info(s) for s in specs],
        }

    def _spec_info(self, spec: Specialist) -> dict[str, Any]:
        backend = self.resolve(spec)
        return {
            "id": spec.id,
            "name": spec.name,
            "provider": backend.provider.config.name,
            "model": backend.model or backend.provider.config.model,
            "adapter": backend.adapter,
            "profile_only": backend.profile_only and spec.adapter is not None,
        }

    # ------------------------------------------------------------------ main entry
    async def run(self, history: list[Message], user_text: str, opts: OrchestratorOptions) -> AsyncIterator[Event]:
        started = time.perf_counter()
        if opts.mode != "auto":
            spec = self.catalog.get(opts.mode)
            decision = RouteDecision(mode="single" if spec.id != "core" else "direct", specialists=[spec.id],
                                     confidence=1.0, method="user")
        else:
            decision = self.router.route(user_text)

        plan: Plan | None = None
        if opts.mode == "auto" and opts.use_planner and decision.mode == "multi":
            core = self.resolve(self.catalog.core)
            yield {"type": "status", "message": "planning"}
            plan = await make_plan(core.provider, self.catalog, user_text, decision.specialists,
                                   model=core.model, max_subtasks=opts.max_subtasks)
            used = list(dict.fromkeys(t.specialist for t in plan.subtasks))
            decision.method = "llm" if plan.method == "llm" else "lexical"
            if len(plan.subtasks) == 1:
                decision.mode = "direct" if used == ["core"] else "single"
                decision.specialists = used
                plan = None
            else:
                decision.specialists = used

        specs = [self.catalog.get(s) for s in decision.specialists]
        yield self._route_event(decision, specs)

        final = AgentRun()
        if plan is None:
            spec = specs[0]
            async for ev in self._run_single(spec, history, user_text, opts, final):
                yield ev
        else:
            yield {"type": "plan", "method": plan.method, "note": plan.note,
                   "subtasks": [{"id": t.id, "specialist": t.specialist, "instruction": t.instruction,
                                 "depends_on": t.depends_on} for t in plan.subtasks]}
            async for ev in self._run_plan(plan, history, user_text, opts, final):
                yield ev

        yield {
            "type": "done",
            "text": final.text,
            "error": final.error,
            "finish_reason": final.finish_reason,
            "private": final.private,
            "specialists": decision.specialists,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }

    # ------------------------------------------------------------------ single specialist
    async def _run_single(self, spec: Specialist, history: list[Message], user_text: str,
                          opts: OrchestratorOptions, final: AgentRun) -> AsyncIterator[Event]:
        backend = self.resolve(spec)
        skill_text, skill_tools, skill_event = self._skills_for(spec, backend, user_text, opts)
        if skill_event:
            yield skill_event
        messages = [self.system_message(spec, opts, skill_text, backend.context_budget), *history,
                    Message(role="user", content=user_text)]
        async for ev in run_agent(
            backend.provider, messages, tools=self._tools_for(spec, opts) + skill_tools, broker=self.broker, run=final,
            adapter=backend.adapter, model=backend.model, temperature=opts.temperature,
            max_tokens=opts.max_tokens, context_budget=backend.context_budget, reasoning=opts.reasoning,
            tag={"specialist": spec.id}, checkpoints=opts.checkpoints,
        ):
            yield ev

    # ------------------------------------------------------------------ multi specialist
    async def _run_subtask(self, task: Subtask, history: list[Message], user_text: str, results: dict[str, str],
                           owners: dict[str, str], opts: OrchestratorOptions,
                           tainted: set[str]) -> AsyncIterator[Event]:
        spec = self.catalog.get(task.specialist)
        backend = self.resolve(spec)
        team_note = ("You are one member of a team of specialists. Answer only your assigned subtask, "
                     "thoroughly and precisely; another model will merge the team's work.")
        deps = "\n\n".join(f"## Result from {self.catalog.get(owners[d]).name}\n{results[d]}"
                           for d in task.depends_on if d in results)
        # what other models wrote after reading the user's files stays as private as the files
        private = [results[d] for d in task.depends_on if d in results and d in tainted]
        recent_msgs = [m for m in history[-6:] if m.role in ("user", "assistant")]
        recent = "\n".join(f"{m.role}: {m.content[:1500]}" for m in recent_msgs)
        private += [m.content[:1500] for m in recent_msgs if m.private]
        content = (
            (f"# Conversation so far\n{recent}\n\n" if recent else "")
            + f"# Overall user request\n{user_text}\n\n# Your subtask\n{task.instruction}"
            + (f"\n\n# Inputs from other specialists\n{deps}" if deps else "")
        )
        skill_text, skill_tools, skill_event = self._skills_for(spec, backend, f"{task.instruction}\n{user_text}", opts)
        messages = [self.system_message(spec, opts, "\n\n".join(p for p in (team_note, skill_text) if p),
                                        backend.context_budget),
                    Message(role="user", content=content, private=private)]
        run = AgentRun()
        yield {"type": "subtask_start", "subtask": task.id, "specialist": spec.id, "name": spec.name,
               "instruction": task.instruction}
        if skill_event:
            yield {**skill_event, "subtask": task.id}
        t0 = time.perf_counter()
        async for ev in run_agent(
            backend.provider, messages, tools=self._tools_for(spec, opts) + skill_tools, broker=self.broker, run=run,
            adapter=backend.adapter, model=backend.model, temperature=opts.temperature,
            max_tokens=opts.max_tokens, context_budget=backend.context_budget, reasoning=opts.reasoning,
            tag={"subtask": task.id, "specialist": spec.id}, checkpoints=opts.checkpoints,
        ):
            yield ev
        results[task.id] = run.text if not run.error else f"(failed: {run.error})\n{run.text}"
        if run.private:
            tainted.add(task.id)
        yield {"type": "subtask_end", "subtask": task.id, "specialist": spec.id, "ok": run.error is None,
               "elapsed_s": round(time.perf_counter() - t0, 3)}

    async def _run_plan(self, plan: Plan, history: list[Message], user_text: str, opts: OrchestratorOptions,
                        final: AgentRun) -> AsyncIterator[Event]:
        results: dict[str, str] = {}
        tainted: set[str] = set()  # subtasks whose model read the user's files
        owners = {t.id: t.specialist for t in plan.subtasks}
        for level in topological_levels(plan.subtasks):
            if opts.parallel and len(level) > 1:
                async for ev in _merge([self._run_subtask(t, history, user_text, results, owners, opts, tainted)
                                    for t in level]):
                    yield ev
            else:
                for task in level:
                    async for ev in self._run_subtask(task, history, user_text, results, owners, opts, tainted):
                        yield ev

        reports = "\n\n".join(
            f"## {self.catalog.get(t.specialist).name} — {t.instruction}\n{results.get(t.id, '')}"
            for t in plan.subtasks
        )
        core = self.catalog.core
        backend = self.resolve(core)
        messages = [
            self.system_message(core, opts, SYNTHESIS_INSTRUCTIONS, backend.context_budget),
            *history,
            Message(role="user", content=f"{user_text}\n\n# Specialist reports\n{reports}",
                    private=[results[t] for t in tainted if results.get(t)]),
        ]
        yield {"type": "synthesis_start"}
        async for ev in run_agent(
            backend.provider, messages, tools=[], broker=self.broker, run=final, adapter=backend.adapter,
            model=backend.model, temperature=opts.temperature, max_tokens=opts.max_tokens,
            context_budget=backend.context_budget, reasoning=opts.reasoning, tag={"specialist": "core"},
        ):
            yield ev


async def _merge(generators: list[AsyncIterator[Event]]) -> AsyncIterator[Event]:
    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def pump(gen: AsyncIterator[Event]) -> None:
        try:
            async for ev in gen:
                await queue.put(ev)
        finally:
            await queue.put(None)

    tasks = [asyncio.create_task(pump(g)) for g in generators]
    remaining = len(tasks)
    try:
        while remaining:
            ev = await queue.get()
            if ev is None:
                remaining -= 1
            else:
                yield ev
    finally:
        for t in tasks:
            t.cancel()
