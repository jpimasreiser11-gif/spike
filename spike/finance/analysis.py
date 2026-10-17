"""Performance and risk numbers from price series: returns, volatility, Sharpe, drawdown, historical VaR,
correlations. Plain formulas on closing prices; no forecasts. Every function says what it assumes."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

PERIODS = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365, "1w": 52}  # crypto trades every day


def simple_returns(closes: list[float]) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    return c[1:] / c[:-1] - 1.0 if len(c) > 1 else np.array([])


def max_drawdown(equity: list[float] | np.ndarray) -> float:
    """The largest fall from a previous peak, as a negative fraction (−0.25 = −25 %)."""
    e = np.asarray(equity, dtype=float)
    if len(e) == 0:
        return 0.0
    peaks = np.maximum.accumulate(e)
    return float(np.min(e / peaks - 1.0))


def metrics(equity: list[float] | np.ndarray, periods_per_year: int, risk_free: float = 0.0) -> dict[str, Any]:
    """Total return, CAGR, annualised volatility, Sharpe (excess over `risk_free` a year, sample std) and max
    drawdown of an equity curve sampled once per period."""
    e = np.asarray(equity, dtype=float)
    if len(e) < 2 or e[0] <= 0:
        return {"total_return": 0.0, "cagr": 0.0, "volatility": 0.0, "sharpe": None, "max_drawdown": 0.0,
                "periods": int(len(e))}
    r = e[1:] / e[:-1] - 1.0
    years = (len(e) - 1) / periods_per_year
    total = float(e[-1] / e[0] - 1.0)
    cagr = float((e[-1] / e[0]) ** (1 / years) - 1.0) if years > 0 and e[-1] > 0 else -1.0
    std = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    vol = std * math.sqrt(periods_per_year)
    excess = float(np.mean(r)) - risk_free / periods_per_year
    sharpe = excess / std * math.sqrt(periods_per_year) if std > 0 else None
    return {"total_return": round(total, 6), "cagr": round(cagr, 6), "volatility": round(vol, 6),
            "sharpe": round(sharpe, 4) if sharpe is not None else None, "max_drawdown": round(max_drawdown(e), 6),
            "periods": int(len(e))}


def align(series: dict[str, list[tuple[int, float]]]) -> tuple[list[int], dict[str, np.ndarray]]:
    """Keep only the timestamps every series has, so returns are compared on the same days."""
    common = set.intersection(*(set(t for t, _ in s) for s in series.values())) if series else set()
    stamps = sorted(common)
    out = {}
    for name, s in series.items():
        by_t = dict(s)
        out[name] = np.array([by_t[t] for t in stamps], dtype=float)
    return stamps, out


def portfolio_risk(series: dict[str, list[tuple[int, float]]], weights: dict[str, float], periods_per_year: int,
                   confidence: float = 0.95) -> dict[str, Any]:
    """Risk of a fixed-weight portfolio (rebalanced every period) from aligned closing prices: annualised
    volatility, historical one-period VaR and expected shortfall at `confidence`, max drawdown, each asset's
    volatility and share of the risk, and the correlation matrix."""
    names = [n for n in weights if n in series]
    if not names:
        raise ValueError("no prices for the assets given")
    total_w = sum(weights[n] for n in names)
    if total_w <= 0:
        raise ValueError("the weights must add up to more than zero")
    w = np.array([weights[n] / total_w for n in names])
    stamps, aligned = align({n: series[n] for n in names})
    if len(stamps) < 3:
        raise ValueError("the price series have fewer than 3 common dates")
    rets = np.column_stack([simple_returns(list(aligned[n])) for n in names])
    port = rets @ w
    cov = np.cov(rets, rowvar=False, ddof=1) if len(names) > 1 else np.array([[np.var(rets[:, 0], ddof=1)]])
    port_var = float(w @ cov @ w)
    contrib = (w * (cov @ w)) / port_var if port_var > 0 else np.zeros(len(names))
    corr = np.corrcoef(rets, rowvar=False) if len(names) > 1 else np.array([[1.0]])
    q = float(np.quantile(port, 1 - confidence))
    tail = port[port <= q]
    equity = np.concatenate([[1.0], np.cumprod(1 + port)])
    ann = math.sqrt(periods_per_year)
    return {
        "assets": names, "weights": {n: round(float(x), 6) for n, x in zip(names, w, strict=True)},
        "observations": int(len(port)), "from_ms": stamps[0], "to_ms": stamps[-1],
        "volatility": round(math.sqrt(port_var) * ann, 6),
        "var": round(-q, 6), "expected_shortfall": round(float(-np.mean(tail)), 6) if len(tail) else None,
        "confidence": confidence, "max_drawdown": round(max_drawdown(equity), 6),
        "total_return": round(float(equity[-1] - 1.0), 6),
        "asset_volatility": {n: round(float(np.std(rets[:, i], ddof=1)) * ann, 6) for i, n in enumerate(names)},
        "risk_share": {n: round(float(c), 6) for n, c in zip(names, contrib, strict=True)},
        "correlation": {a: {b: round(float(corr[i, j]), 4) for j, b in enumerate(names)} for i, a in enumerate(names)},
    }
