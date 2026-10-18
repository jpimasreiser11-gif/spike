"""The acceptance rule of a training config, applied to measured eval results, for `spike adapters install`.

The same function lives in training/spike_train/evaluation.py, which runs in the training environment without
this package; tests/test_evolution.py checks that both give the same verdicts."""

from __future__ import annotations

from typing import Any


def check_acceptance(summary: dict[str, Any], acceptance: dict[str, Any], variant: str,
                     baseline: str = "base") -> tuple[bool, list[str]]:
    """Apply a training config's `acceptance` block to measured results. Missing suites fail."""
    reasons: list[str] = []
    ok = True
    primary = acceptance.get("primary") or {}
    if "min_gain_points" in primary:
        cmp = summary["suites"].get(primary["suite"], {}).get("vs_" + baseline, {}).get(variant)
        if not cmp:
            return False, [f"suite '{primary['suite']}' was not evaluated for {variant}"]
        gain_ok = cmp["delta_points"] >= primary["min_gain_points"]
        p_ok = cmp["p_value"] <= primary.get("max_p_value", 0.05)
        ok &= gain_ok and p_ok
        reasons.append(f"{primary['suite']}: {cmp['delta_points']:+.2f} pts (need ≥ {primary['min_gain_points']}), "
                       f"p = {cmp['p_value']:.4g} (need ≤ {primary.get('max_p_value', 0.05)})")
    regression = acceptance.get("regression") or {}
    if regression:
        cmp = summary["suites"].get(regression["suite"], {}).get("vs_" + baseline, {}).get(variant)
        if not cmp:
            return False, reasons + [f"regression suite '{regression['suite']}' was not evaluated for {variant}"]
        drop_ok = -cmp["delta_points"] <= regression["max_drop_points"]
        ok &= drop_ok
        reasons.append(f"{regression['suite']}: {cmp['delta_points']:+.2f} pts (max drop {regression['max_drop_points']})")
    return ok, reasons
