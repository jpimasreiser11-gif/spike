"""The Forge blueprint: the goal, the requirements SPIKE understood, the steps (who does what, which files each saves)
and the acceptance criteria. The core model drafts it; nothing runs until the user approves it, edited or not."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from spike.core.types import ChatRequest, Message
from spike.orchestrator.planner import ROLES, Subtask, extract_json
from spike.providers.base import Provider
from spike.specialists.catalog import Catalog

MAX_STEPS = 5  # drafted by the model
MAX_USER_STEPS = 8  # after the user's edits
MAX_ITEMS = 8  # requirements, criteria
MAX_FILES = 4  # per step
STEP_ID = re.compile(r"[A-Za-z0-9_-]{1,20}")
FILE_CHARS = re.compile(r"[\w\- .()/]+")


@dataclass
class Blueprint:
    goal: str
    requirements: list[str]
    steps: list[Subtask]
    criteria: list[str]
    method: str = "llm"  # "llm" | "fallback" | "user"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "requirements": self.requirements, "steps": [asdict(s) for s in self.steps],
                "criteria": self.criteria, "method": self.method, "note": self.note}

    @property
    def deliverables(self) -> list[str]:
        return [p for s in self.steps for p in s.deliverables]


def clean_path(raw: str) -> str:
    """A deliverable's path, relative to the folder the file tools write to; ValueError when it is not one."""
    text = str(raw).strip().replace("\\", "/")
    if not text or len(text) > 200 or not FILE_CHARS.fullmatch(text) or text.startswith("/") or ":" in text:
        raise ValueError(f"'{raw}' is not a relative file path")
    path = PurePosixPath(text)
    if any(part in ("..", ".") for part in path.parts) or text.endswith("/"):
        raise ValueError(f"'{raw}' is not a relative file path")
    return str(path)


def blueprint_schema(specialist_ids: list[str], max_steps: int) -> dict[str, Any]:
    texts = {"type": "array", "maxItems": MAX_ITEMS, "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "requirements": texts,
            "steps": {"type": "array", "minItems": 1, "maxItems": max_steps, "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "specialist": {"type": "string", "enum": specialist_ids},
                    "role": {"type": "string", "enum": list(ROLES)},
                    "instruction": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "deliverables": {"type": "array", "maxItems": MAX_FILES, "items": {"type": "string"}},
                },
                "required": ["id", "specialist", "role", "instruction", "depends_on", "deliverables"],
                "additionalProperties": False,
            }},
            "criteria": texts,
        },
        "required": ["goal", "requirements", "steps", "criteria"],
        "additionalProperties": False,
    }


def blueprint_prompt(catalog: Catalog, candidates: list[str], max_steps: int) -> str:
    roster = "\n".join(f"- {s.id}: {s.name} — {s.description}" for s in catalog.specialists.values())
    hint = ", ".join(candidates) if candidates else "none"
    return (
        "You are the planner of SPIKE Forge, a team of specialist models. Turn the user's task into a blueprint "
        "the user will review and approve before any work starts:\n"
        "- goal: the result, in one sentence;\n"
        "- requirements: what the task asks for, explicitly or clearly implied, one per item;\n"
        f"- steps: the fewest steps (1 to {max_steps}), each owned by one specialist, with role research (finds what "
        "others need) or execute (produces part of the result), a self-contained instruction, depends_on for steps "
        "whose output it needs, and deliverables: the files the step must save, as relative paths such as "
        "informe.md or datos/ventas.csv, only when the task asks for a file or a file is the natural result;\n"
        "- criteria: acceptance criteria someone can check by reading the results: concrete numbers, sections, "
        "formats, files.\n"
        "Write the texts in the user's language.\n\n"
        f"Specialists:\n{roster}\n\nA keyword pre-router suggested: {hint}. Override it when it is wrong.\n"
        'Reply with JSON only: {"goal": "...", "requirements": ["..."], "steps": [{"id": "t1", "specialist": "...", '
        '"role": "execute", "instruction": "...", "depends_on": [], "deliverables": ["..."]}], "criteria": ["..."]}'
    )


def _texts(value: Any, limit: int = MAX_ITEMS) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:500] for v in value if str(v).strip()][:limit]


def _steps(raw_steps: Any, catalog: Catalog, limit: int, strict: bool) -> list[Subtask]:
    """Validated steps; in strict mode (the user's blueprint) a problem raises ValueError, otherwise it gives []."""
    def bad(message: str) -> list[Subtask]:
        if strict:
            raise ValueError(message)
        return []

    if not isinstance(raw_steps, list) or not raw_steps:
        return bad("a blueprint needs at least one step")
    if len(raw_steps) > limit:
        if strict:
            raise ValueError(f"a blueprint has at most {limit} steps")
        raw_steps = raw_steps[:limit]
    steps: list[Subtask] = []
    seen: set[str] = set()
    files: set[str] = set()
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            return bad(f"step {i + 1} is not an object")
        sid = str(raw.get("id") or f"t{i + 1}").strip()
        spec = str(raw.get("specialist") or "")
        instruction = str(raw.get("instruction") or "").strip()
        if not STEP_ID.fullmatch(sid) or sid in seen:
            return bad(f"step {i + 1} needs a unique id of letters, digits, - or _")
        if spec not in catalog.specialists:
            return bad(f"step {sid}: unknown specialist '{spec}'")
        if not instruction:
            return bad(f"step {sid} has no instruction")
        deps = [str(d) for d in raw.get("depends_on") or []]
        if strict and (later := [d for d in deps if d not in seen]):
            raise ValueError(f"step {sid} depends on {', '.join(later)}, which is not an earlier step")
        role = raw.get("role")
        if role not in ROLES:
            if strict and role is not None:
                raise ValueError(f"step {sid}: role must be research or execute")
            role = "execute"
        paths: list[str] = []
        for p in (raw.get("deliverables") or [])[:MAX_FILES if not strict else None]:
            try:
                path = clean_path(p)
            except ValueError as exc:
                if strict:
                    raise ValueError(f"step {sid}: {exc}") from exc
                continue
            if path in files:
                if strict:
                    raise ValueError(f"two steps save {path}")
                continue
            files.add(path)
            paths.append(path)
        if strict and len(paths) > MAX_FILES:
            raise ValueError(f"step {sid} saves more than {MAX_FILES} files")
        steps.append(Subtask(id=sid, specialist=spec, instruction=instruction[:4000],
                             depends_on=[d for d in deps if d in seen], role=role, deliverables=paths))
        seen.add(sid)
    return steps


def validate_blueprint(obj: dict | None, catalog: Catalog, max_steps: int = MAX_STEPS) -> Blueprint | None:
    """The model's draft, cleaned up; None when it has no usable step."""
    if not obj:
        return None
    steps = _steps(obj.get("steps"), catalog, max_steps, strict=False)
    if not steps:
        return None
    return Blueprint(goal=str(obj.get("goal") or "").strip()[:500], requirements=_texts(obj.get("requirements")),
                     steps=steps, criteria=_texts(obj.get("criteria")))


def from_user(obj: Any, catalog: Catalog) -> Blueprint:
    """The blueprint the user approved (maybe edited): checked strictly, ValueError says what is wrong."""
    if not isinstance(obj, dict):
        raise ValueError("the blueprint must be an object")
    for key in ("requirements", "criteria"):
        if not isinstance(obj.get(key, []), list):
            raise ValueError(f"'{key}' must be a list of texts")
        if len(obj.get(key, [])) > 2 * MAX_ITEMS:
            raise ValueError(f"'{key}' has more than {2 * MAX_ITEMS} items")
    steps = _steps(obj.get("steps"), catalog, MAX_USER_STEPS, strict=True)
    return Blueprint(goal=str(obj.get("goal") or "").strip()[:500],
                     requirements=_texts(obj.get("requirements"), 2 * MAX_ITEMS), steps=steps,
                     criteria=_texts(obj.get("criteria"), 2 * MAX_ITEMS), method="user",
                     note=str(obj.get("note") or "")[:300])


def fallback_blueprint(task: str, candidates: list[str], note: str) -> Blueprint:
    spec = candidates[0] if candidates else "core"
    return Blueprint(goal=task.strip().splitlines()[0][:200] if task.strip() else "", requirements=[],
                     steps=[Subtask(id="t1", specialist=spec, instruction=task.strip()[:4000])], criteria=[],
                     method="fallback", note=note)


async def make_blueprint(provider: Provider, catalog: Catalog, task: str, candidates: list[str], *,
                         model: str | None = None, max_steps: int = MAX_STEPS) -> Blueprint:
    request = ChatRequest(
        messages=[Message(role="system", content=blueprint_prompt(catalog, candidates, max_steps)),
                  Message(role="user", content=task)],
        model=model, temperature=0.0, max_tokens=1500,
        json_schema=blueprint_schema(list(catalog.specialists), max_steps), reasoning=False,
    )
    try:
        text, _ = await provider.complete(request)
    except Exception as exc:
        return fallback_blueprint(task, candidates, f"planner unavailable: {exc}")
    blueprint = validate_blueprint(extract_json(text), catalog, max_steps)
    return blueprint or fallback_blueprint(task, candidates, "planner output was invalid")

