"""SPIKE's own backtester (written for SPIKE; nothing from freqtrade or vectorbt). Long-only, one asset, all in or
all out. A strategy decides at a bar's close and the trade happens at the next bar's open, so it never uses a price
it could not have known; fees and slippage are charged on every trade. Past results do not predict returns."""

from __future__ import annotations

from typing import Any

from spike.finance.analysis import PERIODS, metrics

Candle = tuple[int, float, float, float, float, float]  # ms, open, high, low, close, volume
STRATEGIES: dict[str, dict[str, float]] = {
    "buy_hold": {},
    "sma_cross": {"fast": 20, "slow": 50},  # in while the fast average is above the slow one
    "rsi": {"period": 14, "low": 30, "high": 70},  # in below `low`, out above `high`
}
NOTE = ("Simulated on past prices: long only, all in or all out, decided at a bar's close and traded at the next "
        "bar's open, with fees and slippage on every trade. Past results do not predict future returns.")


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        out.append(total / n if i >= n - 1 else None)
    return out


def rsi(values: list[float], n: int) -> list[float | None]:
    """Wilder's RSI: the first average is a simple mean of `n` changes, then smoothed."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_g, avg_l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(values)):
        if i > n:
            avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
            avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1 + avg_g / avg_l)
    return out


def check_params(strategy: str, given: dict[str, Any] | None) -> dict[str, float]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}'; one of: {', '.join(STRATEGIES)}")
    params = dict(STRATEGIES[strategy])
    for key, value in (given or {}).items():
        if key not in params:
            raise ValueError(f"'{strategy}' has no parameter '{key}' (it takes: {', '.join(params) or 'none'})")
        try:
            params[key] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'{key}' must be a number") from exc
    if strategy == "sma_cross" and (not (1 <= params["fast"] < params["slow"])
                                    or params["fast"] != int(params["fast"]) or params["slow"] != int(params["slow"])):
        raise ValueError("sma_cross needs whole numbers with 1 ≤ fast < slow")
    if strategy == "rsi" and (params["period"] < 2 or params["period"] != int(params["period"])):
        raise ValueError("rsi needs a whole period of at least 2")
    if strategy == "rsi" and not (0 < params["low"] < params["high"] < 100):
        raise ValueError("rsi needs 0 < low < high < 100")
    return params


def signals(strategy: str, closes: list[float], params: dict[str, float]) -> list[int]:
    """1 = be in the market after this bar's close, 0 = be out."""
    if strategy == "buy_hold":
        return [1] * len(closes)
    if strategy == "sma_cross":
        fast, slow = sma(closes, int(params["fast"])), sma(closes, int(params["slow"]))
        return [1 if f is not None and s is not None and f > s else 0 for f, s in zip(fast, slow, strict=True)]
    values, out, state = rsi(closes, int(params["period"])), [], 0
    for v in values:
        if v is not None and v < params["low"]:
            state = 1
        elif v is not None and v > params["high"]:
            state = 0
        out.append(state)
    return out


def simulate(candles: list[Candle], signal: list[int], fee: float, slippage: float,
             cash: float) -> tuple[list[float], list[dict[str, Any]], int]:
    units, equity, trades, bars_in = 0.0, [], [], 0
    for i, (t, o, _h, _l, c, _v) in enumerate(candles):
        if i > 0:
            want = signal[i - 1]
            if want == 1 and units == 0 and cash > 0:
                price = o * (1 + slippage)
                paid = cash * fee
                units, cash = (cash - paid) / price, 0.0
                trades.append({"t": t, "side": "buy", "price": round(price, 8), "units": units, "fee": round(paid, 8)})
            elif want == 0 and units > 0:
                price = o * (1 - slippage)
                proceeds = units * price
                paid = proceeds * fee
                trades.append({"t": t, "side": "sell", "price": round(price, 8), "units": units, "fee": round(paid, 8)})
                units, cash = 0.0, proceeds - paid
        bars_in += units > 0
        equity.append(cash + units * c)
    return equity, trades, bars_in


def run_backtest(candles: list[Candle], strategy: str, params: dict[str, Any] | None = None, *, fee: float = 0.001,
                 slippage: float = 0.0005, cash: float = 10_000.0, timeframe: str = "1d") -> dict[str, Any]:
    p = check_params(strategy, params)
    if not (0 <= fee < 0.05 and 0 <= slippage < 0.05):
        raise ValueError("fee and slippage are fractions below 0.05 (0.001 = 0.1 %)")
    warmup = int(p.get("slow", p.get("period", 0)))
    if len(candles) < max(3, warmup + 2):
        raise ValueError(f"{len(candles)} bars are too few for this strategy (needs at least {max(3, warmup + 2)})")
    closes = [c[4] for c in candles]
    periods = PERIODS.get(timeframe, 365)
    equity, trades, bars_in = simulate(candles, signals(strategy, closes, p), fee, slippage, cash)
    bench, _, _ = simulate(candles, [1] * len(candles), fee, slippage, cash)
    sells = [t for t in trades if t["side"] == "sell"]
    buys = [t for t in trades if t["side"] == "buy"]
    wins = sum(1 for b, s in zip(buys, sells, strict=False) if s["units"] * s["price"] - s["fee"] > b["units"] * b["price"] + b["fee"])
    return {
        "strategy": strategy, "params": p, "timeframe": timeframe, "bars": len(candles),
        "from_ms": candles[0][0], "to_ms": candles[-1][0], "fee": fee, "slippage": slippage, "start_cash": cash,
        "final_equity": round(equity[-1], 2), **metrics(equity, periods),
        "trades": len(trades), "round_trips": len(sells), "win_rate": round(wins / len(sells), 4) if sells else None,
        "exposure": round(bars_in / len(candles), 4),
        "buy_hold": {"final_equity": round(bench[-1], 2), **metrics(bench, periods)},
        "last_trades": [{**t, "units": round(t["units"], 8)} for t in trades[-10:]],
        "note": NOTE,
    }
