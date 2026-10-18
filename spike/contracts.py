"""Answer contracts: an answer that must be JSON following a schema is checked, and asked for once more with the
errors when it does not follow it. Providers constrain the output when they can (llama.cpp grammars, OpenAI
`json_schema`), but a prompt-only provider or a cut-off answer can still break it, so the check is SPIKE's own."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import SchemaError
from jsonschema.validators import validator_for

REPAIR = ("Your answer does not follow the required JSON schema:\n{errors}\n\nReply again with only the JSON value "
          "that follows the schema, no other text.")
FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def schema_error(schema: Any) -> str | None:
    """Why this is not a usable JSON Schema, or None."""
    if not isinstance(schema, dict):
        return "the schema must be a JSON object"
    try:
        validator_for(schema).check_schema(schema)
    except SchemaError as exc:
        return f"invalid JSON Schema: {exc.message}"
    return None


def check(text: str, schema: dict[str, Any]) -> tuple[Any, list[str]]:
    """(the parsed value, what breaks the schema); an empty list means the answer follows it."""
    fenced = FENCE.search(text)
    raw = (fenced.group(1) if fenced else text).strip()
    try:
        value = json.loads(raw)
    except ValueError as exc:
        return None, [f"not valid JSON ({getattr(exc, 'msg', str(exc))})"]
    validator = validator_for(schema)(schema)
    errors = sorted(validator.iter_errors(value), key=lambda e: [str(p) for p in e.absolute_path])
    return value, [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors[:5]]


def repair_prompt(errors: list[str]) -> str:
    return REPAIR.format(errors="\n".join(f"- {e}" for e in errors))
