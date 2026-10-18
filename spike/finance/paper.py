"""Paper trading: a simulated account on this computer that buys and sells at real public prices, with fees and
slippage, so a strategy can be tried without money. Nothing here talks to an exchange's private API."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_CASH = 10_000.0
DEFAULT_QUOTE = "USDT"
FEE = 0.001  # 0.1 % a trade, a common taker fee
SLIPPAGE = 0.0005
DUST = 1e-12


class PaperError(ValueError):
    pass


class PaperAccount:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
CREATE TABLE IF NOT EXISTS paper_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_orders (
  id TEXT PRIMARY KEY, created REAL NOT NULL, exchange TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
  type TEXT NOT NULL, amount REAL NOT NULL, limit_price REAL, status TEXT NOT NULL, fill_price REAL, fee REAL,
  filled REAL, note TEXT NOT NULL DEFAULT ''
);""")
        self._db.commit()
        self._lock = threading.Lock()
        if self._get("balances") is None:
            self.reset()

    def _get(self, key: str) -> Any:
        row = self._db.execute("SELECT value FROM paper_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def _set(self, key: str, value: Any) -> None:
        self._db.execute("INSERT OR REPLACE INTO paper_state VALUES (?,?)", (key, json.dumps(value)))

    def reset(self, cash: float = DEFAULT_CASH, quote: str = DEFAULT_QUOTE) -> dict[str, Any]:
        if cash <= 0:
            raise PaperError("the starting cash must be positive")
        with self._lock:
            self._db.execute("DELETE FROM paper_orders")
            self._set("balances", {quote.upper(): float(cash)})
            self._set("start", {"cash": float(cash), "quote": quote.upper(), "time": time.time()})
            self._db.commit()
        return self.state()

    def state(self) -> dict[str, Any]:
        return {"balances": self._get("balances") or {}, "start": self._get("start") or {}}

    def orders(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM paper_orders" + (" WHERE status=?" if status else "") + " ORDER BY created DESC LIMIT ?"
        return [dict(r) for r in self._db.execute(sql, (status, limit) if status else (limit,)).fetchall()]

    def _fill(self, balances: dict[str, float], symbol: str, side: str, amount: float, price: float,
              slip: bool = True) -> tuple[float, float]:
        """Apply a fill to the balances; returns (fill price, fee in the quote currency). Market orders pay
        slippage; limit orders fill at their price or better."""
        base, quote = symbol.split("/")
        fill = price if not slip else price * (1 + SLIPPAGE) if side == "buy" else price * (1 - SLIPPAGE)
        cost = amount * fill
        fee = cost * FEE
        if side == "buy":
            if balances.get(quote, 0.0) + DUST < cost + fee:
                raise PaperError(f"not enough {quote}: the order needs {cost + fee:.2f}, the account has "
                                 f"{balances.get(quote, 0.0):.2f}")
            balances[quote] = balances.get(quote, 0.0) - cost - fee
            balances[base] = balances.get(base, 0.0) + amount
        else:
            if balances.get(base, 0.0) + DUST < amount:
                raise PaperError(f"not enough {base}: selling {amount:g}, the account has {balances.get(base, 0.0):g}")
            balances[base] = balances.get(base, 0.0) - amount
            balances[quote] = balances.get(quote, 0.0) + cost - fee
        for k in [k for k, v in balances.items() if abs(v) < DUST]:
            balances[k] = 0.0
        return fill, fee

    def place(self, exchange: str, symbol: str, side: str, amount: float, price_now: float, type_: str = "market",
              limit_price: float | None = None, note: str = "") -> dict[str, Any]:
        """A market order fills now at `price_now` (with slippage); a limit order fills now if the price is already
        there, else it waits for `refresh`."""
        if side not in ("buy", "sell"):
            raise PaperError("side must be buy or sell")
        if type_ not in ("market", "limit"):
            raise PaperError("type must be market or limit")
        if not amount or amount <= 0:
            raise PaperError("the amount must be positive")
        if type_ == "limit" and (limit_price is None or limit_price <= 0):
            raise PaperError("a limit order needs a positive limit price")
        order = {"id": uuid.uuid4().hex[:12], "created": time.time(), "exchange": exchange, "symbol": symbol,
                 "side": side, "type": type_, "amount": float(amount), "limit_price": limit_price, "status": "open",
                 "fill_price": None, "fee": None, "filled": 0.0, "note": note[:200]}
        with self._lock:
            balances = self._get("balances")
            marketable = type_ == "market" or (side == "buy" and price_now <= limit_price) or \
                (side == "sell" and price_now >= limit_price)
            if marketable:
                price = price_now if type_ == "market" else min(price_now, limit_price) if side == "buy" \
                    else max(price_now, limit_price)
                order["fill_price"], order["fee"] = self._fill(balances, symbol, side, amount, price, type_ == "market")
                order["status"], order["filled"] = "filled", float(amount)
                self._set("balances", balances)
            self._db.execute("INSERT INTO paper_orders VALUES (:id,:created,:exchange,:symbol,:side,:type,:amount,"
                             ":limit_price,:status,:fill_price,:fee,:filled,:note)", order)
            self._db.commit()
        return order

    def cancel(self, order_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone()
            if row is None or row["status"] != "open":
                raise PaperError("no open order with that id")
            self._db.execute("UPDATE paper_orders SET status='cancelled' WHERE id=?", (order_id,))
            self._db.commit()
        return {**dict(row), "status": "cancelled"}

    def refresh(self, prices: dict[str, float]) -> list[dict[str, Any]]:
        """Fill the open limit orders the price `prices[symbol]` has reached; an order the account can no longer
        pay for is cancelled with the reason."""
        done = []
        with self._lock:
            balances = self._get("balances")
            for row in self._db.execute("SELECT * FROM paper_orders WHERE status='open' ORDER BY created").fetchall():
                price = prices.get(row["symbol"])
                if price is None:
                    continue
                if (row["side"] == "buy" and price <= row["limit_price"]) or \
                        (row["side"] == "sell" and price >= row["limit_price"]):
                    try:
                        fill, fee = self._fill(balances, row["symbol"], row["side"], row["amount"], row["limit_price"],
                                               slip=False)
                        self._db.execute("UPDATE paper_orders SET status='filled', fill_price=?, fee=?, filled=? "
                                         "WHERE id=?", (fill, fee, row["amount"], row["id"]))
                        done.append({**dict(row), "status": "filled", "fill_price": fill, "fee": fee})
                    except PaperError as exc:
                        self._db.execute("UPDATE paper_orders SET status='cancelled', note=? WHERE id=?",
                                         (str(exc)[:200], row["id"]))
            self._set("balances", balances)
            self._db.commit()
        return done

    def valuation(self, prices: dict[str, float]) -> dict[str, Any]:
        """Value of every balance in the account's quote currency, from `prices` of ASSET/QUOTE."""
        st = self.state()
        quote = st["start"].get("quote", DEFAULT_QUOTE)
        rows, total, missing = [], 0.0, []
        for asset, qty in sorted(st["balances"].items()):
            if qty == 0:
                continue
            price = 1.0 if asset == quote else prices.get(f"{asset}/{quote}")
            if price is None:
                missing.append(asset)
                continue
            rows.append({"asset": asset, "quantity": qty, "price": price, "value": round(qty * price, 2)})
            total += qty * price
        start = st["start"].get("cash", 0.0)
        return {"quote": quote, "positions": rows, "total": round(total, 2), "start_cash": start,
                "pnl": round(total - start, 2) if not missing else None,
                "pnl_pct": round((total / start - 1) * 100, 2) if start and not missing else None,
                "unpriced": missing}

    def close(self) -> None:
        self._db.close()
