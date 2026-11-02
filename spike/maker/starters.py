"""Starter Blender scripts. Each is a plain, original bpy script in `blender_scripts/`: a docstring, then the numbers
it can be reshaped with, one per line as `NAME = value  # low..high what it is`, then the code. A model that asks for
a starter names it and gives values; SPIKE checks every value against its range and rewrites that line, so the
saved script is readable and runs by itself in Blender."""

from __future__ import annotations

import ast
import functools
import math
import re
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).with_name("blender_scripts")
NUMBER = r"-?\d+(?:\.\d+)?"
LINE = re.compile(rf"^([A-Z][A-Z0-9_]*) = ({NUMBER})  # ({NUMBER})\.\.({NUMBER}) (.+)$", re.MULTILINE)


class StarterError(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    key: str  # what the model calls it: height
    const: str  # the line in the script: HEIGHT
    default: float
    low: float
    high: float
    help: str
    integer: bool  # the default has no decimal point: a count

    def text(self) -> str:
        return f"{self.key} {self.low:g}-{self.high:g} ({self.default:g})"


@dataclass(frozen=True)
class Starter:
    id: str
    summary: str
    params: tuple[Param, ...]
    source: str


@functools.cache
def starters() -> dict[str, Starter]:
    """The starter scripts that ship with SPIKE, by id (the file name without .py)."""
    found: dict[str, Starter] = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.stem == "render_driver":
            continue
        source = path.read_text(encoding="utf-8")
        summary = (ast.get_docstring(ast.parse(source)) or "").replace("\n", " ").split(". ")[0].rstrip(".")
        params = tuple(Param(m[1].lower(), m[1], float(m[2]) if "." in m[2] else int(m[2]), float(m[3]), float(m[4]),
                             m[5], "." not in m[2]) for m in LINE.finditer(source))
        found[path.stem] = Starter(path.stem, summary, params, source)
    return found


def catalog() -> str:
    """The starters and their numbers (name, range, default), in a few lines for the tool's description."""
    return "\n".join(f"- {s.id}: {s.summary}. Numbers: " + ", ".join(p.text() for p in s.params)
                     for s in starters().values())


def build(starter_id: str, values: object = None) -> str:
    """The script of a starter with the given numbers (the others keep their defaults)."""
    found = starters().get(starter_id)
    if found is None:
        raise StarterError(f"unknown starter '{starter_id}': use one of {', '.join(starters())}")
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise StarterError("params must be an object of numbers, e.g. {\"height\": 3}")
    by_key = {p.key: p for p in found.params}
    unknown = sorted(str(k) for k in values if k not in by_key)
    if unknown:
        raise StarterError(f"{starter_id} has no number named {', '.join(unknown)}: use {', '.join(by_key)}")
    chosen = {}
    for key, value in values.items():
        param = by_key[key]
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise StarterError(f"{key} must be a number")
        if not param.low <= value <= param.high:
            raise StarterError(f"{key} must be between {param.low:g} and {param.high:g}, not {value:g}")
        if param.integer and value != int(value):
            raise StarterError(f"{key} must be a whole number")
        chosen[param.const] = str(int(value)) if param.integer else repr(float(value))

    def put(match: re.Match[str]) -> str:
        return match[0].replace(f"{match[1]} = {match[2]}", f"{match[1]} = {chosen[match[1]]}", 1) \
            if match[1] in chosen else match[0]

    return LINE.sub(put, found.source)
