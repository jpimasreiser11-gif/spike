"""Evolution over HTTP, for the parts added after level 3: tool strategy (EV3), candidate prompt versions (EV8) and the
personal adapter's data (EV6). Kept apart from `app.py` like the memory API: `create_evolution_router` gets a function
that returns the app's state. Training itself is not an endpoint: it takes hours and runs from `spike evolve
personal-adapter`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class CandidateIn(BaseModel):
    instructions: list[str] = Field(default_factory=list, max_length=8)
    skills: dict[str, str] = Field(default_factory=dict)


class ActivateIn(BaseModel):
    version: int | None = None


class MarkIn(BaseModel):
    conversation: str


class ExcludeIn(BaseModel):
    ref: str = Field(min_length=1, max_length=300)
    excluded: bool = True


def create_evolution_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    # ---------------------------------------------------------------- EV3: tool strategy
    @router.get("/api/evolution/strategy")
    async def strategy_table() -> dict:
        return get_state().evolution.strategy_overview()

    @router.post("/api/evolution/strategy/learn")
    async def learn_strategy() -> dict:
        return get_state().learn_strategy()

    @router.delete("/api/evolution/strategy")
    async def reset_strategy() -> dict:
        return {"deleted": get_state().reset_strategy()}

    # ---------------------------------------------------------------- EV8: candidate prompt versions
    @router.post("/api/evolution/prompts/{specialist}/candidate")
    async def propose_prompt(specialist: str, body: CandidateIn) -> dict:
        try:
            return get_state().propose_prompt(specialist, body.instructions, body.skills)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/evolution/prompts/{specialist}/activate")
    async def activate_prompt(specialist: str, body: ActivateIn) -> dict:
        """Compare the candidate with the version in use on the user's eval questions and use it only if it passes.
        One model job at a time, like the optimiser, so the computer stays usable."""
        state = get_state()
        if state.optimizing:
            raise HTTPException(409, "an optimisation is already running")
        state.optimizing = True
        try:
            return await state.activate_prompt(specialist, body.version)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            state.optimizing = False

    # ---------------------------------------------------------------- EV6: personal adapter data
    @router.get("/api/evolution/personal")
    async def personal() -> dict:
        return get_state().personal_overview()

    @router.post("/api/evolution/personal/marks")
    async def mark_chat(body: MarkIn) -> dict:
        from spike.evolution import personal as pa

        state = get_state()
        if not state.evolution_settings()["personal_adapter"]:
            raise HTTPException(409, "turn on the personal adapter in Settings → Evolución first")
        try:
            return pa.mark_chat(state.evolution.store, state.store, body.conversation)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.delete("/api/evolution/personal/marks/{conversation}")
    async def unmark_chat(conversation: str) -> dict:
        from spike.evolution import personal as pa

        if not pa.unmark_chat(get_state().evolution.store, conversation):
            raise HTTPException(404, "that chat is not marked")
        return {"ok": True}

    @router.put("/api/evolution/personal/exclusions")
    async def exclude(body: ExcludeIn) -> dict:
        from spike.evolution import personal as pa

        state = get_state()
        known = {e["id"] for e in pa.build_set(state.evolution.store, state.store,
                                               bool(state.evolution_settings()["training_data"]))["entries"]}
        if body.ref not in known:
            raise HTTPException(404, "that example is not in the personal set")
        pa.set_excluded(state.evolution.store, body.ref, body.excluded)
        return {"ok": True}

    return router
