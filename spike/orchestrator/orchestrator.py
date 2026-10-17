"""The SPIKE orchestrator: route -> (plan) -> run specialists -> synthesize, streaming every step."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from spike.agent.loop import AgentRun, Event, run_agent
from spike.core.types import Message
from spike.orchestrator.planner import Plan, Subtask, make_plan, topological_levels
from spike.orchestrator.router import LexicalRouter, RouteDecision
from spike.providers.base import Provider
from spike.specialists.catalog import Catalog, Specialist
from spike.tools.base import PermissionBroker, ToolRegistry


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


SYNTHESIS_INSTRUCTIONS = (
    "You are writing the final answer for the user. Specialist reports are provided below. Merge them into "
    "one coherent, well-structured answer in the user's language. Resolve contradictions explicitly, keep "
    "every important caveat and uncertainty the specialists raised, do not add facts they did not provide "
    "unless you are confident, and do not mention internal subtask ids."
)


class Orchestrator:
    def __init__(self, catalog: Catalog, resolve: BackendResolver, tools: ToolRegistry, broker: PermissionBroker,
                 router: LexicalRouter | None = None):
        self.catalog = catalog
        self.resolve = resolve
        self.tools = tools
        self.broker = broker
        self.router = router or LexicalRouter(catalog)

    # ------------------------------------------------------------------ prompts
    def system_prompt(self, spec: Specialist, opts: OrchestratorOptions, extra: str = "") -> str:
        parts = [spec.system_prompt]
        if opts.custom_instructions.strip():
            parts.append("# Instructions from the user (always follow them)\n" + opts.custom_instructions.strip())
        if opts.specialist_instructions.get(spec.id, "").strip():
            parts.append(f"# Instructions for {spec.name}\n" + opts.specialist_instructions[spec.id].strip())
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    def _tools_for(self, spec: Specialist, opts: OrchestratorOptions):
        return self.tools.subset(spec.tools) if opts.tools_enabled else []

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
            "specialists": decision.specialists,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }

    # ------------------------------------------------------------------ single specialist
    async def _run_single(self, spec: Specialist, history: list[Message], user_text: str,
                          opts: OrchestratorOptions, final: AgentRun) -> AsyncIterator[Event]:
        backend = self.resolve(spec)
        messages = [Message(role="system", content=self.system_prompt(spec, opts)), *history,
                    Message(role="user", content=user_text)]
        async for ev in run_agent(
            backend.provider, messages, tools=self._tools_for(spec, opts), broker=self.broker, run=final,
            adapter=backend.adapter, model=backend.model, temperature=opts.temperature,
            max_tokens=opts.max_tokens, context_budget=backend.context_budget, reasoning=opts.reasoning,
            tag={"specialist": spec.id},
        ):
            yield ev

    # ------------------------------------------------------------------ multi specialist
    async def _run_subtask(self, task: Subtask, history: list[Message], user_text: str, results: dict[str, str],
                           owners: dict[str, str], opts: OrchestratorOptions) -> AsyncIterator[Event]:
        spec = self.catalog.get(task.specialist)
        backend = self.resolve(spec)
        team_note = ("You are one member of a team of specialists. Answer only your assigned subtask, "
                     "thoroughly and precisely; another model will merge the team's work.")
        deps = "\n\n".join(f"## Result from {self.catalog.get(owners[d]).name}\n{results[d]}"
                           for d in task.depends_on if d in results)
        recent = "\n".join(f"{m.role}: {m.content[:1500]}" for m in history[-6:] if m.role in ("user", "assistant"))
        content = (
            (f"# Conversation so far\n{recent}\n\n" if recent else "")
            + f"# Overall user request\n{user_text}\n\n# Your subtask\n{task.instruction}"
            + (f"\n\n# Inputs from other specialists\n{deps}" if deps else "")
        )
        messages = [Message(role="system", content=self.system_prompt(spec, opts, team_note)),
                    Message(role="user", content=content)]
        run = AgentRun()
        yield {"type": "subtask_start", "subtask": task.id, "specialist": spec.id, "name": spec.name,
               "instruction": task.instruction}
        t0 = time.perf_counter()
        async for ev in run_agent(
            backend.provider, messages, tools=self._tools_for(spec, opts), broker=self.broker, run=run,
            adapter=backend.adapter, model=backend.model, temperature=opts.temperature,
            max_tokens=opts.max_tokens, context_budget=backend.context_budget, reasoning=opts.reasoning,
            tag={"subtask": task.id, "specialist": spec.id},
        ):
            yield ev
        results[task.id] = run.text if not run.error else f"(failed: {run.error})\n{run.text}"
        yield {"type": "subtask_end", "subtask": task.id, "specialist": spec.id, "ok": run.error is None,
               "elapsed_s": round(time.perf_counter() - t0, 3)}

    async def _run_plan(self, plan: Plan, history: list[Message], user_text: str, opts: OrchestratorOptions,
                        final: AgentRun) -> AsyncIterator[Event]:
        results: dict[str, str] = {}
        owners = {t.id: t.specialist for t in plan.subtasks}
        for level in topological_levels(plan.subtasks):
            if opts.parallel and len(level) > 1:
                async for ev in _merge([self._run_subtask(t, history, user_text, results, owners, opts) for t in level]):
                    yield ev
            else:
                for task in level:
                    async for ev in self._run_subtask(task, history, user_text, results, owners, opts):
                        yield ev

        reports = "\n\n".join(
            f"## {self.catalog.get(t.specialist).name} — {t.instruction}\n{results.get(t.id, '')}"
            for t in plan.subtasks
        )
        core = self.catalog.core
        backend = self.resolve(core)
        messages = [
            Message(role="system", content=self.system_prompt(core, opts, SYNTHESIS_INSTRUCTIONS)),
            *history,
            Message(role="user", content=f"{user_text}\n\n# Specialist reports\n{reports}"),
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
