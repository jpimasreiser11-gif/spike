"""Lab routes: read-only preview, single-use explicit execution, local history and JSON export.

Quotes live for five minutes in this app process. Execution rejects changed provider settings, prices or specialist
bindings. No endpoint lists models, refreshes adapters, starts a local engine or schedules background calls.
"""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from spike.core.context import estimate_tokens
from spike.core.types import ChatRequest, Message
from spike.lab import (
    CONTEXT_PROMPT,
    MAX_OUTPUT,
    PROBES,
    ProbeProvider,
    measure,
    probe_capabilities,
    probe_request,
)
from spike.providers.anthropic import AnthropicProvider
from spike.providers.guard import GuardedProvider, call_cost


class TargetIn(BaseModel):
    specialist: str = "core"
    provider_id: str | None = None


class CaseIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    expected: str | None = Field(default=None, max_length=8000)


class PreviewIn(BaseModel):
    kind: Literal["compare", "probe"] = "compare"
    prompt: str = Field(default="", max_length=8000)
    cases: list[CaseIn] = Field(default_factory=list, max_length=16)
    targets: list[TargetIn] = Field(min_length=1, max_length=8)


class ExecuteIn(BaseModel):
    quote_id: str


def create_lab_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/lab")
    quotes: dict[str, dict] = {}

    def resolve(body: PreviewIn) -> list[dict]:
        state, targets = get_state(), []
        for target in body.targets:
            spec = state.catalog.specialists.get(target.specialist)
            if spec is None:
                raise HTTPException(400, "invalid_target")
            pid, model = state.binding(spec, target.provider_id)
            if state.provider_config(pid) is None:
                raise HTTPException(400, "invalid_target")
            provider = state.provider(pid)
            adapter = spec.adapter if (body.kind == "compare" and provider.capabilities.adapters and spec.adapter
                                      in state.installed_adapters.get(pid, set())) else None
            targets.append({"specialist": spec.id, "provider_id": pid, "model": model or provider.config.model,
                            "adapter": adapter, "system_prompt": spec.system_prompt,
                            "config": copy.deepcopy(state.provider_config(pid))})
        return targets

    def cases_for(body: PreviewIn) -> list[CaseIn]:
        cases = body.cases or ([CaseIn(prompt=body.prompt)] if body.prompt.strip() else [])
        if body.kind == "compare" and (not cases or len(cases) * len(body.targets) > 32):
            raise HTTPException(400, "invalid_cases")
        if body.kind == "probe" and len(body.targets) != 1:
            raise HTTPException(400, "one_probe_target")
        return cases

    @router.post("/preview")
    async def preview(body: PreviewIn) -> dict:
        cases = cases_for(body)
        targets = resolve(body)
        state = get_state()
        costs, blocked, calls = [], False, 0
        for target in targets:
            provider = state.provider(target["provider_id"])
            blocked |= bool(provider.blocked())
            if body.kind == "probe":
                native = isinstance(provider.inner, AnthropicProvider)
                inputs = [sum(estimate_tokens(m.content) for m in probe_request(target["model"], cap, native).messages)
                          for cap in probe_capabilities(provider.inner)]
            else:
                inputs = [estimate_tokens(target["system_prompt"]) + estimate_tokens(c.prompt) for c in cases]
            calls += len(inputs)
            costs.extend(call_cost(provider.limits(), n, MAX_OUTPUT) for n in inputs)
        now = time.time()
        for key in list(quotes):
            if quotes[key]["expires"] < now:
                del quotes[key]
        if len(quotes) >= 100:
            del quotes[next(iter(quotes))]
        qid = uuid.uuid4().hex
        quotes[qid] = {"body": body, "targets": targets, "expires": now + 300}
        return {"id": qid, "calls": calls, "blocked": blocked,
                "estimated_cost": sum(costs) if costs and all(c is not None for c in costs) else None,
                "targets": [{k: t[k] for k in ("specialist", "provider_id", "model", "adapter")} for t in targets]}

    @router.post("/execute")
    async def execute(body: ExecuteIn) -> dict:
        quote = quotes.pop(body.quote_id, None)
        if quote is None or quote["expires"] < time.time():
            raise HTTPException(409, "expired_quote")
        data = quote["body"]
        targets = resolve(data)
        if targets != quote["targets"]:
            raise HTTPException(409, "changed_quote")
        state, rows = get_state(), []
        if any(state.provider(t["provider_id"]).blocked() for t in targets):
            raise HTTPException(403, "provider_blocked")
        for target in targets:
            provider = state.provider(target["provider_id"])
            identity = {k: target[k] for k in ("specialist", "provider_id", "model", "adapter")}
            if data.kind == "probe":
                for cap in PROBES:
                    if cap not in probe_capabilities(provider.inner):
                        rows.append({**identity, "capability": cap, "status": "untested"})
                        continue
                    guarded = GuardedProvider(ProbeProvider(provider.inner, cap), state.store, provider.limits)
                    request = probe_request(target["model"], cap, isinstance(provider.inner, AnthropicProvider))
                    result = await measure(guarded, request)
                    result["status"] = result.pop("output") if result["status"] == "ok" else "failed"
                    rows.append({**identity, **result, "capability": cap,
                                 **({"context_tokens_tested": estimate_tokens(CONTEXT_PROMPT)} if cap == "context" else {})})
            else:
                for index, case in enumerate(cases_for(data)):
                    request = ChatRequest(messages=[Message(role="system", content=target["system_prompt"]),
                                                    Message(role="user", content=case.prompt)], model=target["model"],
                                          adapter=target["adapter"], max_tokens=MAX_OUTPUT, temperature=0)
                    result = await measure(provider, request)
                    score = None if case.expected is None or result["status"] != "ok" else int(
                        result["output"].strip() == case.expected.strip())
                    rows.append({**identity, **result, "case": index + 1, "prompt": case.prompt,
                                 "expected": case.expected, "score": score})
        run = {"id": uuid.uuid4().hex, "created": time.time(), "kind": data.kind, "rows": rows}
        state.store.set_setting("lab_runs", [run, *state.store.get_setting("lab_runs", [])][:50])
        return run

    @router.get("/runs")
    async def runs() -> list[dict]:
        return get_state().store.get_setting("lab_runs", [])

    @router.get("/runs/{run_id}/export")
    async def export(run_id: str) -> JSONResponse:
        run = next((r for r in get_state().store.get_setting("lab_runs", []) if r["id"] == run_id), None)
        if run is None:
            raise HTTPException(404, "unknown_run")
        return JSONResponse(run, headers={"Content-Disposition": f'attachment; filename="lab-{run_id}.json"'})

    return router
