"""Validation of the plain (non-nested-module) settings behind Settings > General, Tools, Specialists, Memory, Evolution
and Engine. Every check raises `ValueError("invalid setting '<key>': <rule>")`; the web app turns the key into a
message in the user's language. Nothing is stored unless the whole patch is valid."""

from __future__ import annotations

import math
from collections.abc import Collection
from typing import Any

MAX_TEXT = 20000  # custom and per-specialist instructions, in characters
TEMPERATURE = (0.0, 2.0)
MAX_TOKENS = (64, 32768)
SKILL_MODES = ("auto", "router", "model", "off")
POLICIES = ("allow", "ask", "deny")
EMBEDDINGS = ("auto", "off")
KV_TYPES = ("f16", "q8_0", "q4_0")
MEMORY_FLAGS = ("enabled", "auto_summary", "learn")
EVOLUTION_KEYS = ("enabled", "auto_router", "training_data", "auto_strategy", "personal_adapter")
RUNTIME_KEYS = ("model", "adapters", "context", "threads", "gpu_layers", "kv_cache_type", "port")
BOOLEANS = ("use_planner", "parallel", "tools_enabled")


def bad(key: str, rule: str) -> ValueError:
    return ValueError(f"invalid setting '{key}': {rule}")


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(key: str, value: Any, what: str = "text") -> str:
    if not isinstance(value, str):
        raise bad(key, f"must be {what}")
    if len(value) > MAX_TEXT:
        raise bad(key, f"at most {MAX_TEXT} characters")
    return value


def _in_range(key: str, value: Any, low: int, high: int) -> None:
    if not _int(value) or not low <= value <= high:
        raise bad(key, f"must be a whole number from {low} to {high}")


def _flags(key: str, value: Any, flags: Collection[str], current: dict[str, Any], defaults: dict[str, Any],
           choices: dict[str, tuple[str, ...]] | None = None) -> dict:
    """`value` merged over what is stored: `flags` must be booleans, `choices` one of the listed words."""
    choices = choices or {}
    names = [*flags, *choices]
    if not isinstance(value, dict) or set(value) - set(names):
        raise bad(key, f"takes {', '.join(names)}")
    for name in flags:
        if name in value and not isinstance(value[name], bool):
            raise bad(key, f"'{name}' must be true or false")
    for name, words in choices.items():
        if name in value and value[name] not in words:
            raise bad(key, f"'{name}' must be one of {', '.join(words)}")
    return {**defaults, **current, **value}


def clean_runtime(value: Any, current: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(RUNTIME_KEYS):
        raise bad("local_runtime", f"takes {', '.join(RUNTIME_KEYS)}")
    out = {**defaults, **current, **value}
    if not isinstance(out["model"], str) or len(out["model"]) > 1000:
        raise bad("local_runtime", "'model' must be a file path")
    if not isinstance(out["adapters"], list) or not all(isinstance(p, str) for p in out["adapters"]):
        raise bad("local_runtime", "'adapters' must be a list of file paths")
    for name, low, high in (("context", 512, 1_048_576), ("threads", 1, 256), ("gpu_layers", 0, 999)):
        if out[name] is not None and not (_int(out[name]) and low <= out[name] <= high):
            raise bad("local_runtime", f"'{name}' must be a whole number from {low} to {high}, or empty")
    if out["kv_cache_type"] not in KV_TYPES:
        raise bad("local_runtime", f"'kv_cache_type' must be one of {', '.join(KV_TYPES)}")
    if not _int(out["port"]) or not 1024 <= out["port"] <= 65535:
        raise bad("local_runtime", "'port' must be a whole number from 1024 to 65535")
    return out


def clean_patch(patch: dict[str, Any], settings: dict[str, Any], defaults: dict[str, Any],
                provider_ids: Collection[str]) -> dict[str, Any]:
    """The patch with every plain setting checked (and memory/evolution/local_runtime merged over what is stored)."""
    out = dict(patch)
    for key in BOOLEANS:
        if key in out and not isinstance(out[key], bool):
            raise bad(key, "must be true or false")
    if "reasoning" in out and out["reasoning"] is not None and not isinstance(out["reasoning"], bool):
        raise bad("reasoning", "must be true, false or empty")
    if "custom_instructions" in out:
        _text("custom_instructions", out["custom_instructions"])
    if out.get("temperature") is not None:
        t = out["temperature"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not (
                TEMPERATURE[0] <= t <= TEMPERATURE[1]):
            raise bad("temperature", f"must be a number from {TEMPERATURE[0]:g} to {TEMPERATURE[1]:g} or empty")
    if out.get("max_tokens") is not None:
        _in_range("max_tokens", out["max_tokens"], *MAX_TOKENS)
    if "skill_mode" in out and out["skill_mode"] not in SKILL_MODES:
        raise bad("skill_mode", f"must be one of {', '.join(SKILL_MODES)}")
    if "default_provider" in out:
        pid = out["default_provider"]
        if not isinstance(pid, str):
            raise bad("default_provider", "must be a provider id")
        if pid not in provider_ids:
            raise ValueError(f"unknown provider '{pid}'")
    if "specialist_instructions" in out:
        given = out["specialist_instructions"]
        if not all(isinstance(k, str) and 0 < len(k) <= 80 for k in given):
            raise bad("specialist_instructions", "keys must be specialist ids")
        for value in given.values():
            _text("specialist_instructions", value)
    if "specialist_bindings" in out:
        for bound in out["specialist_bindings"].values():
            if not isinstance(bound, dict) or set(bound) - {"provider_id", "model"} or not all(
                    isinstance(v, str) for v in bound.values()):
                raise bad("specialist_bindings", "each specialist takes {provider_id, model}")
            if bound.get("provider_id") and bound["provider_id"] not in provider_ids:
                raise ValueError(f"unknown provider '{bound['provider_id']}'")
    if "tool_policies" in out:
        for name, policy in out["tool_policies"].items():
            if not isinstance(name, str) or not 0 < len(name) <= 200 or policy not in POLICIES:
                raise bad("tool_policies", f"each tool takes one of {', '.join(POLICIES)}")
    if "disabled_skills" in out and not all(isinstance(n, str) and 0 < len(n) <= 200 for n in out["disabled_skills"]):
        raise bad("disabled_skills", "must be a list of skill names")
    if "memory" in out:
        out["memory"] = _flags("memory", out["memory"], MEMORY_FLAGS, settings.get("memory") or {}, defaults["memory"],
                               {"embeddings": EMBEDDINGS})
    if "evolution" in out:
        out["evolution"] = _flags("evolution", out["evolution"], EVOLUTION_KEYS, settings.get("evolution") or {},
                                  defaults["evolution"])
    if "local_runtime" in out:
        out["local_runtime"] = clean_runtime(out["local_runtime"], settings.get("local_runtime") or {},
                                             defaults["local_runtime"])
    return out
