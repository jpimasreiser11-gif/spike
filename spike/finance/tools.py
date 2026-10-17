"""Spike Finance's tools: public prices and history, backtests, portfolio risk, the paper account, and proposals
of real orders that only the user can confirm in the app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spike.finance.analysis import PERIODS, metrics, portfolio_risk
from spike.finance.backtest import STRATEGIES, run_backtest
from spike.finance.live import LiveError, LiveTrading
from spike.finance.market import (
    EXCHANGES,
    TIMEFRAMES,
    Market,
    MarketError,
    ccxt_exchange,
    check_symbol,
    load_csv,
)
from spike.finance.paper import PaperAccount, PaperError
from spike.store.secrets import SecretStore
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import Workspace

DEFAULTS: dict[str, Any] = {"exchange": "kraken"}


class Finance:
    """Market data, the paper account and real orders, kept in `$SPIKE_HOME/finance/`."""

    def __init__(self, home: Path, secrets: SecretStore, settings, factory=ccxt_exchange):
        self.settings = settings  # () -> the "finance" setting
        self.market = Market(home / "finance" / "market.db", factory)
        self.paper = PaperAccount(home / "finance" / "paper.db")
        self.live = LiveTrading(home / "finance" / "live.db", secrets, lambda: self.settings().get("live", {}), factory)

    def exchange(self, given: str | None = None) -> str:
        ex = (given or self.settings().get("exchange") or DEFAULTS["exchange"]).strip().lower()
        if ex not in EXCHANGES:
            raise MarketError(f"exchange must be one of {', '.join(EXCHANGES)}")
        return ex

    async def prices(self, symbols: set[str], exchange: str | None = None) -> dict[str, float]:
        return {s: (await self.market.ticker(self.exchange(exchange), s))["last"] for s in sorted(symbols)}

    def close(self) -> None:
        self.market.close()
        self.paper.close()
        self.live.close()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _date(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


class _FinanceTool(Tool):
    risk = "network"
    default_policy = "allow"  # public market data and the simulated account; real orders only propose

    def __init__(self, finance: Finance, workspace: Workspace):
        self.finance, self.workspace = finance, workspace

    async def candles(self, args: dict[str, Any], days_default: int = 365) -> tuple[str, list, str, bool]:
        """(label, candles, timeframe, from a user file) from `csv` (a workspace file) or `symbol`."""
        timeframe = str(args.get("timeframe") or "1d")
        if args.get("csv"):
            path = self.workspace.resolve(str(args["csv"]))
            return path.name, load_csv(path.read_text(encoding="utf-8", errors="replace")), timeframe, True
        if not args.get("symbol"):
            raise MarketError("give a market symbol (e.g. BTC/USDT) or a csv file from the workspace")
        ex = self.finance.exchange(args.get("exchange"))
        days = int(args.get("days") or days_default)
        data = await self.finance.market.ohlcv(ex, str(args["symbol"]), timeframe, days)
        if len(data) < 2:
            raise MarketError(f"{ex} returned no history for {args['symbol']}")
        return f"{check_symbol(str(args['symbol']))} on {ex}", data, timeframe, False

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            return await self.act(args)
        except (MarketError, PaperError, LiveError, ValueError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")

    async def act(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


SOURCE = {"symbol": {"type": "string", "description": "market, e.g. BTC/USDT or ETH/EUR"},
          "csv": {"type": "string", "description": "instead of symbol: a CSV in the workspace with date and close"},
          "exchange": {"type": "string", "enum": EXCHANGES}, "timeframe": {"type": "string", "enum": list(TIMEFRAMES)},
          "days": {"type": "integer"}}


class MarketPrice(_FinanceTool):
    name = "market_price"
    description = "Current public price of a crypto market (last, bid, ask, 24 h change) from an exchange."
    parameters = {"type": "object", "properties": {"symbol": SOURCE["symbol"], "exchange": SOURCE["exchange"]},
                  "required": ["symbol"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        t = await self.finance.market.ticker(self.finance.exchange(args.get("exchange")), str(args.get("symbol", "")))
        return ToolResult(ok=True, content=_dump(t))


class MarketHistory(_FinanceTool):
    name = "market_history"
    description = ("Price history summary of a market or of a CSV of prices: dates, last close, change, high, low, "
                   "annualised volatility, max drawdown and the last closes.")
    parameters = {"type": "object", "properties": SOURCE}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        label, data, tf, private = await self.candles(args, 90)
        closes = [c[4] for c in data]
        m = metrics(closes, PERIODS.get(tf, 365))
        out = {"market": label, "timeframe": tf, "from": _date(data[0][0]), "to": _date(data[-1][0]),
               "bars": len(data), "last_close": closes[-1], "change": m["total_return"],
               "high": max(c[2] for c in data), "low": min(c[3] for c in data), "volatility": m["volatility"],
               "max_drawdown": m["max_drawdown"], "last_closes": [[_date(c[0]), c[4]] for c in data[-10:]]}
        text = _dump(out)
        return ToolResult(ok=True, content=text, private=[text] if private else [])


class Backtest(_FinanceTool):
    name = "backtest"
    description = ("Simulate a long-only strategy on past prices with fees and slippage, compared with buy and hold. "
                   f"Strategies: {', '.join(f'{k} {v}' if v else k for k, v in STRATEGIES.items())}. Past results do "
                   "not predict future returns; say so.")
    parameters = {"type": "object", "properties": {
        **SOURCE, "strategy": {"type": "string", "enum": list(STRATEGIES)},
        "params": {"type": "object", "description": "strategy parameters, e.g. {\"fast\": 20, \"slow\": 50}"},
        "fee": {"type": "number", "description": "per trade, 0.001 = 0.1 %"}, "slippage": {"type": "number"},
        "cash": {"type": "number"}}, "required": ["strategy"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        label, data, tf, private = await self.candles(args)
        result = run_backtest(data, str(args["strategy"]), args.get("params"), fee=float(args.get("fee", 0.001)),
                              slippage=float(args.get("slippage", 0.0005)), cash=float(args.get("cash", 10_000)),
                              timeframe=tf)
        result = {"market": label, **result, "from": _date(result.pop("from_ms")), "to": _date(result.pop("to_ms"))}
        result["last_trades"] = [{**t, "t": _date(t["t"])} for t in result["last_trades"]]
        text = _dump(result)
        return ToolResult(ok=True, content=text, private=[text] if private else [])


class PortfolioRisk(_FinanceTool):
    name = "portfolio_risk"
    description = ("Risk of a portfolio from past daily prices: volatility, historical VaR and expected shortfall "
                   "(95 %), max drawdown, each asset's share of the risk and correlations. Give weights or quantities.")
    parameters = {"type": "object", "properties": {
        "weights": {"type": "object", "description": "market → weight, e.g. {\"BTC/USDT\": 0.6, \"ETH/USDT\": 0.4}"},
        "quantities": {"type": "object", "description": "market → units held; weighted by today's value"},
        "exchange": SOURCE["exchange"], "days": {"type": "integer"}}}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        given = args.get("weights") or args.get("quantities")
        if not isinstance(given, dict) or not given:
            raise ValueError("give weights or quantities per market")
        if len(given) > 12:
            raise ValueError("at most 12 markets")
        ex = self.finance.exchange(args.get("exchange"))
        days = int(args.get("days") or 365)
        series = {}
        for symbol in given:
            data = await self.finance.market.ohlcv(ex, str(symbol), "1d", days)
            series[check_symbol(str(symbol))] = [(c[0], c[4]) for c in data]
        amounts = {check_symbol(str(k)): float(v) for k, v in given.items()}
        weights = amounts if args.get("weights") else {k: q * series[k][-1][1] for k, q in amounts.items() if series[k]}
        result = portfolio_risk(series, weights, 365)
        result = {"exchange": ex, **result, "from": _date(result.pop("from_ms")), "to": _date(result.pop("to_ms")),
                  "note": "Historical, daily, fixed weights; past risk does not bound future losses."}
        return ToolResult(ok=True, content=_dump(result))


class PaperOrder(_FinanceTool):
    name = "paper_order"
    description = ("Buy or sell in SPIKE's paper account (simulated money, real public prices, 0.1 % fee). Use it to "
                   "try a strategy; it never touches a real exchange account.")
    parameters = {"type": "object", "properties": {
        "symbol": SOURCE["symbol"], "side": {"type": "string", "enum": ["buy", "sell"]},
        "amount": {"type": "number", "description": "units of the base asset (0.01 BTC)"},
        "type": {"type": "string", "enum": ["market", "limit"]}, "limit_price": {"type": "number"},
        "exchange": SOURCE["exchange"]}, "required": ["symbol", "side", "amount"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        ex = self.finance.exchange(args.get("exchange"))
        symbol = check_symbol(str(args.get("symbol", "")))
        price = (await self.finance.market.ticker(ex, symbol))["last"]
        filled = self.finance.paper.refresh({symbol: price})
        order = self.finance.paper.place(ex, symbol, str(args.get("side")), float(args.get("amount") or 0), price,
                                         str(args.get("type") or "market"), args.get("limit_price"))
        return ToolResult(ok=True, content=_dump({"order": order, "price_now": price, "also_filled": filled,
                                                  "balances": self.finance.paper.state()["balances"]}))


class PaperPortfolio(_FinanceTool):
    name = "paper_portfolio"
    description = "The paper account: balances valued at current prices, profit or loss, open and recent orders."
    parameters = {"type": "object", "properties": {"exchange": SOURCE["exchange"]}}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        paper = self.finance.paper
        st = paper.state()
        quote = st["start"].get("quote", "USDT")
        open_symbols = {o["symbol"] for o in paper.orders(status="open")}
        held = {f"{a}/{quote}" for a, q in st["balances"].items() if q and a != quote}
        prices = await self.finance.prices(open_symbols | held, args.get("exchange")) if open_symbols | held else {}
        filled = paper.refresh(prices)
        return ToolResult(ok=True, content=_dump({"valuation": paper.valuation(prices), "just_filled": filled,
                                                  "open_orders": paper.orders(status="open"),
                                                  "recent_orders": paper.orders(limit=10)}))


class ProposeLiveOrder(_FinanceTool):
    name = "propose_live_order"
    description = ("Propose a REAL order on the user's exchange account. It is not placed: the user sees it in the "
                   "app and only their click confirms it. Works only if the user turned real orders on in Settings "
                   "(with limits and a key that cannot withdraw); otherwise use paper_order.")
    parameters = PaperOrder.parameters | {"properties": {k: v for k, v in PaperOrder.parameters["properties"].items()
                                                         if k != "exchange"}}
    interactive_only = True  # someone must be in the app to confirm it: never offered to /v1 or MCP callers

    async def act(self, args: dict[str, Any]) -> ToolResult:
        live: LiveTrading = self.finance.live
        problems = live.problems()
        if problems:
            raise LiveError("; ".join(problems) + ". Use paper_order to simulate it.")
        cfg = live.config()
        symbol = check_symbol(str(args.get("symbol", "")))
        price = (await self.finance.market.ticker(cfg["exchange"], symbol))["last"]
        order = live.propose(symbol, str(args.get("side")), float(args.get("amount") or 0), price,
                             str(args.get("type") or "market"), args.get("limit_price"))
        text = (f"Proposed, NOT placed: {order['side']} {order['amount']:g} {symbol} on {order['exchange']}"
                f"{' (test network)' if order['sandbox'] else ' (REAL funds)'}, about {order['notional']:.2f}. "
                "The user must confirm it in the app within 10 minutes; tell them it is waiting for their click.")
        return ToolResult(ok=True, content=text, data={"ui": {"kind": "live_order", "order": order}})


def finance_tools(finance: Finance, workspace: Workspace) -> list[Tool]:
    return [cls(finance, workspace) for cls in (MarketPrice, MarketHistory, Backtest, PortfolioRisk, PaperOrder,
                                                PaperPortfolio, ProposeLiveOrder)]
