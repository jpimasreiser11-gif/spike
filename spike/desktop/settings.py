"""The `desktop` settings: whether desktop actions exist at all (off by default), which API provider does them, how many
steps one task may take at most, and which computer-use tool form that provider's model gets (`auto` follows the
documented model table)."""

from __future__ import annotations

from typing import Any

from spike.desktop.adapters import CHOICES

DEFAULTS: dict[str, Any] = {"enabled": False, "provider_id": "", "max_steps": 20, "tool": "auto"}
HARD_MAX_STEPS = 50  # whatever the setting says, a task never takes more steps than this


def clean(value: Any) -> dict[str, Any]:
    """Validated desktop settings, with the defaults for what is missing."""
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError(f"desktop settings take {', '.join(DEFAULTS)}")
    out = {**DEFAULTS, **value}
    if not isinstance(out["enabled"], bool):
        raise ValueError("'enabled' must be true or false")
    if not isinstance(out["provider_id"], str) or len(out["provider_id"]) > 60:
        raise ValueError("'provider_id' must be a provider id")
    n = out["max_steps"]
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= HARD_MAX_STEPS:
        raise ValueError(f"'max_steps' must be a whole number from 1 to {HARD_MAX_STEPS}")
    if out["tool"] not in CHOICES:
        raise ValueError(f"'tool' must be one of {', '.join(CHOICES)}")
    return out
