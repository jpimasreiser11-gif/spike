"""Stage-2 planner: asks the core model for a small, validated task graph over the available specialists."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from spike.core.types import ChatRequest, Message
from spike.providers.base import Provider
from spike.specialists.catalog import Catalog


@dataclass
class Subtask:
    id: str
    specialist: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Plan:
    subtasks: list[Subtask]
    method: str  # "llm" | "fallback"
    note: str = ""


def plan_schema(specialist_ids: list[str], max_subtasks: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_subtasks,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "specialist": {"type": "string", "enum": specialist_ids},
                        "instruction": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "specialist", "instruction", "depends_on"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["subtasks"],
        "additionalProperties": False,
    }


def planner_prompt(catalog: Catalog, candidates: list[str], max_subtasks: int) -> str:
    roster = "\n".join(
        f"- {s.id}: {s.name} — {s.description}" for s in catalog.specialists.values() if s.id != "core"
    )
    hint = ", ".join(candidates) if candidates else "none"
    return (
        "You are the planner of SPIKE, a team of specialist models. Split the user's request into the fewest "
        f"subtasks needed (1 to {max_subtasks}), each owned by exactly one specialist. Use one subtask when one "
        "specialist can answer everything. Each instruction must be self-contained and say exactly what to "
        "produce. Use depends_on only when a subtask needs another subtask's output.\n\n"
        f"Specialists:\n{roster}\n\nA keyword pre-router suggested: {hint}. Override it when it is wrong.\n"
        'Reply with JSON only: {"subtasks": [{"id": "t1", "specialist": "...", "instruction": "...", "depends_on": []}]}'
    )


def extract_json(text: str) -> dict | None:
    text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text[text.find("{"): text.rfind("}") + 1]
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def validate_plan(obj: dict | None, catalog: Catalog, max_subtasks: int) -> list[Subtask] | None:
    if not obj or not isinstance(obj.get("subtasks"), list) or not obj["subtasks"]:
        return None
    subtasks: list[Subtask] = []
    seen: set[str] = set()
    for i, raw in enumerate(obj["subtasks"][:max_subtasks]):
        if not isinstance(raw, dict):
            return None
        sid = str(raw.get("id") or f"t{i + 1}")
        spec = str(raw.get("specialist", ""))
        instruction = str(raw.get("instruction", "")).strip()
        if spec not in catalog.specialists or not instruction or sid in seen:
            return None
        deps = [str(d) for d in raw.get("depends_on") or [] if str(d) in seen]  # only backward edges: acyclic
        subtasks.append(Subtask(id=sid, specialist=spec, instruction=instruction, depends_on=deps))
        seen.add(sid)
    return subtasks


def fallback_plan(candidates: list[str], user_text: str) -> Plan:
    subtasks = [
        Subtask(id=f"t{i + 1}", specialist=sid,
                instruction=f"Answer the parts of this request that fall within your domain:\n\n{user_text}")
        for i, sid in enumerate(candidates)
    ]
    return Plan(subtasks=subtasks, method="fallback")


async def make_plan(
    provider: Provider,
    catalog: Catalog,
    user_text: str,
    candidates: list[str],
    *,
    model: str | None = None,
    max_subtasks: int = 4,
) -> Plan:
    ids = [s for s in catalog.specialists if s != "core"]
    request = ChatRequest(
        messages=[
            Message(role="system", content=planner_prompt(catalog, candidates, max_subtasks)),
            Message(role="user", content=user_text),
        ],
        model=model,
        temperature=0.0,
        max_tokens=800,
        json_schema=plan_schema(ids, max_subtasks),
        reasoning=False,
    )
    try:
        text, _ = await provider.complete(request)
    except Exception as exc:
        plan = fallback_plan(candidates or ["core"], user_text)
        plan.note = f"planner unavailable: {exc}"
        return plan
    subtasks = validate_plan(extract_json(text), catalog, max_subtasks)
    if subtasks is None:
        plan = fallback_plan(candidates or ["core"], user_text)
        plan.note = "planner output was invalid"
        return plan
    return Plan(subtasks=subtasks, method="llm")


def topological_levels(subtasks: list[Subtask]) -> list[list[Subtask]]:
    """Group subtasks into levels that can run concurrently (validated plans are acyclic)."""
    done: set[str] = set()
    remaining = list(subtasks)
    levels: list[list[Subtask]] = []
    while remaining:
        level = [t for t in remaining if all(d in done for d in t.depends_on)]
        if not level:  # defensive: break cycles by running the rest sequentially
            level = remaining[:1]
        levels.append(level)
        done.update(t.id for t in level)
        remaining = [t for t in remaining if t.id not in done]
    return levels
