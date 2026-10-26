"""Small, deterministic forecasting baselines without fitted third-party models.

SES and additive Holt use fixed alpha=beta=0.5 by default; Holt starts with the first observation and first
increment. Rolling origins use identical expanding training windows and complete horizon-sized test windows
for every method. MAE counts every held-out prediction (overlapping windows included); ties use METHODS order.
Observations must be ordered, equally spaced and finite; dates/frequency are the caller's responsibility.
"""

from __future__ import annotations

import math
from typing import Any

from spike.analytics.engine import DataError

METHODS = ("naive", "seasonal_naive", "drift", "ses", "holt")
MAX_VALUES = 10_000
MAX_HORIZON = 100
MAX_ORIGINS = 100


def _integer(value: Any, name: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise DataError(f"{name} must be an integer from 1 to {maximum}")


def forecast(values: list[float], horizon: int, method: str = "naive", *, season: int = 1,
             alpha: float = 0.5, beta: float = 0.5) -> list[float]:
    """Project h steps: last value, last season, endpoint slope, SES level, or additive Holt level/trend."""
    _integer(horizon, "horizon", MAX_HORIZON)
    _integer(season, "season", MAX_VALUES)
    if (not values or len(values) > MAX_VALUES or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                     or not math.isfinite(v) for v in values)):
        raise DataError(f"forecast needs 1 to {MAX_VALUES} finite numeric observations")
    if not 0 <= alpha <= 1 or not 0 <= beta <= 1:
        raise DataError("alpha and beta must be between 0 and 1")
    y = [float(v) for v in values]
    if method == "naive":
        return [y[-1]] * horizon
    if method == "seasonal_naive":
        if len(y) < season:
            raise DataError("seasonal naive needs a complete season")
        return [y[-season + i % season] for i in range(horizon)]
    if method in ("drift", "holt") and len(y) < 2:
        raise DataError("drift and Holt need at least two observations")
    if method == "drift":
        slope = (y[-1] - y[0]) / (len(y) - 1)
        return [y[-1] + slope * h for h in range(1, horizon + 1)]
    if method == "ses":
        level = y[0]
        for value in y[1:]:
            level = alpha * value + (1 - alpha) * level
        return [level] * horizon
    if method == "holt":
        level, trend = y[0], y[1] - y[0]
        for value in y[1:]:
            previous = level
            level = alpha * value + (1 - alpha) * (level + trend)
            trend = beta * (level - previous) + (1 - beta) * trend
        return [level + h * trend for h in range(1, horizon + 1)]
    raise DataError(f"forecast method must be one of {', '.join(METHODS)}")


def backtest(values: list[float], horizon: int, *, season: int = 1) -> dict[str, Any]:
    """Choose the smallest rolling-origin MAE; retain scores and absolute errors for independent checking.

    At most the last 100 valid origins are evaluated, keeping interactive work bounded. No test observation is
    used by its own training window. All five candidates must have enough training and one full test window.
    """
    forecast(values, horizon, season=season)
    start = max(2, season)
    origins = list(range(start, len(values) - horizon + 1))[-MAX_ORIGINS:]
    if not origins:
        raise DataError("backtest needs at least max(2, season) + horizon observations")
    table = []
    for method in METHODS:
        errors = []
        for origin in origins:
            predicted = forecast(values[:origin], horizon, method, season=season)
            errors.extend(abs(actual - pred) for actual, pred in zip(
                values[origin:origin + horizon], predicted, strict=True))
        table.append({"method": method, "mae": sum(errors) / len(errors), "folds": len(origins),
                      "errors": errors})
    best = min(table, key=lambda row: row["mae"])["method"]
    return {"method": best, "forecast": forecast(values, horizon, best, season=season), "backtest": table,
            "origins": origins, "horizon": horizon, "season": season, "alpha": 0.5, "beta": 0.5}
