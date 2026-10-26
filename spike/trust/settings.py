"""The `trust` settings: whether answers get claim labels, when a low-confidence answer offers a second opinion from an
external provider (`escalate_unchecked`: how many unchecked claims make it low-confidence), and the optional model
pass that may lower labels."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {"enabled": True, "escalate": True, "escalate_unchecked": 3, "model_pass": False}
MAX_UNCHECKED = 50


def clean(value: Any) -> dict[str, Any]:
    """Validated trust settings, with the defaults for what is missing."""
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError(f"trust settings take {', '.join(DEFAULTS)}")
    out = {**DEFAULTS, **value}
    for k in ("enabled", "escalate", "model_pass"):
        if not isinstance(out[k], bool):
            raise ValueError(f"'{k}' must be true or false")
    n = out["escalate_unchecked"]
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_UNCHECKED:
        raise ValueError(f"'escalate_unchecked' must be a whole number from 1 to {MAX_UNCHECKED}")
    return out
