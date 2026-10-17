"""Real orders on an exchange. Off unless the user turns them on in Settings, with an API key that cannot
withdraw funds, a per-order and a per-day limit and a list of markets. SPIKE never places one by itself: a model
can only propose an order, and only the user's click on that proposal in the app places it (`confirm`), after
every check runs again. The exchange's test network is the default."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spike.finance.market import EXCHANGES, ccxt_exchange, check_symbol
from spike.store.secrets import SecretStore

DEFAULTS: dict[str, Any] = {"enabled": False, "exchange": "", "sandbox": True, "no_withdrawal": False,
                            "max_order": 100.0, "max_day": 300.0, "symbols": []}
TESTNETS = ["binance", "okx", "bybit"]  # the exchanges whose test network ccxt 4.5 can switch to
PROPOSAL_TTL_S = 600  # a proposal not confirmed in 10 minutes expires: prices move
DAY_S = 86400


class LiveError(ValueError):
    pass


def clean(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate the live trading settings (`finance.live`)."""
    out = {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if k in DEFAULTS}}
    unknown = set(cfg or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown live trading settings: {sorted(unknown)}")
    if out["exchange"] and out["exchange"] not in EXCHANGES:
        raise ValueError(f"exchange must be one of {', '.join(EXCHANGES)}")
    for key in ("enabled", "sandbox", "no_withdrawal"):
        if not isinstance(out[key], bool):
            raise ValueError(f"'{key}' must be true or false")
    for key in ("max_order", "max_day"):
        try:
            out[key] = float(out[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'{key}' must be a number") from exc
        if out[key] <= 0:
            raise ValueError(f"'{key}' must be positive")
    if out["max_order"] > out["max_day"]:
        raise ValueError("the per-order limit cannot be above the daily limit")
    if not isinstance(out["symbols"], list):
        raise ValueError("'symbols' must be a list")
    try:
        out["symbols"] = sorted({check_symbol(str(s)) for s in out["symbols"]})
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if out["enabled"] and not (out["exchange"] and out["no_withdrawal"] and out["symbols"]):
        raise ValueError("real orders need an exchange, at least one market and your confirmation that the key "
                         "cannot withdraw funds")
    return out


def key_names(exchange: str) -> tuple[str, str]:
    return f"finance:{exchange}:apiKey", f"finance:{exchange}:secret"


class LiveTrading:
    def __init__(self, path: Path, secrets: SecretStore, settings: Callable[[], dict[str, Any]],
                 factory: Callable[..., Any] = ccxt_exchange):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
CREATE TABLE IF NOT EXISTS live_orders (
  id TEXT PRIMARY KEY, created REAL NOT NULL, exchange TEXT NOT NULL, sandbox INTEGER NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL, type TEXT NOT NULL, amount REAL NOT NULL, price REAL, est_price REAL NOT NULL,
  notional REAL NOT NULL, status TEXT NOT NULL, decided REAL, result TEXT NOT NULL DEFAULT '', conversation_id TEXT
);
CREATE TABLE IF NOT EXISTS live_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);""")
        self._db.commit()
        self._lock = threading.Lock()
        self.secrets, self.settings, self.factory = secrets, settings, factory

    # ------------------------------------------------------------------ state
    def config(self) -> dict[str, Any]:
        return clean(self.settings())

    def has_key(self, exchange: str) -> bool:
        k, s = key_names(exchange)
        return bool(exchange) and self.secrets.has(k) and self.secrets.has(s)

    def set_key(self, exchange: str, api_key: str, secret: str) -> None:
        if exchange not in EXCHANGES:
            raise LiveError(f"exchange must be one of {', '.join(EXCHANGES)}")
        if not api_key.strip() or not secret.strip():
            raise LiveError("both the API key and its secret are needed")
        k, s = key_names(exchange)
        self.secrets.set(k, api_key.strip())
        self.secrets.set(s, secret.strip())
        self._set_state(f"withdrawals:{exchange}", "")  # a new key has not been checked

    def delete_key(self, exchange: str) -> None:
        for name in key_names(exchange):
            self.secrets.delete(name)

    def _state(self, key: str) -> str:
        row = self._db.execute("SELECT value FROM live_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

    def _set_state(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO live_state VALUES (?,?)", (key, value))
            self._db.commit()

    def spent_today(self, now: float | None = None) -> float:
        since = (now or time.time()) - DAY_S
        row = self._db.execute("SELECT COALESCE(SUM(notional), 0) AS s FROM live_orders WHERE status='placed' AND "
                               "decided >= ?", (since,)).fetchone()
        return float(row["s"])

    def problems(self, cfg: dict[str, Any] | None = None) -> list[str]:
        """Why real orders cannot be placed now (empty: they can, each one confirmed by the user)."""
        return [text for _, text in self._problems(cfg or self.config())]

    def _problems(self, cfg: dict[str, Any]) -> list[tuple[str, str]]:
        out = []
        if not cfg["enabled"]:
            out.append(("off", "real orders are off (Settings → Finance)"))
        if not cfg["exchange"]:
            out.append(("no_exchange", "no exchange chosen"))
        elif not self.has_key(cfg["exchange"]):
            out.append(("no_key", f"no API key saved for {cfg['exchange']}"))
        if not cfg["no_withdrawal"]:
            out.append(("withdrawal_unconfirmed", "you have not confirmed that the key cannot withdraw funds"))
        if cfg["exchange"] and cfg["sandbox"] and cfg["exchange"] not in TESTNETS:
            out.append(("no_testnet", f"{cfg['exchange']} has no test network ({', '.join(TESTNETS)} do); turn test "
                                      "mode off only if you mean to trade real funds"))
        if cfg["exchange"] and self._state(f"withdrawals:{cfg['exchange']}") == "yes":
            out.append(("can_withdraw", "the exchange says this key can withdraw funds: create one without that "
                                        "permission"))
        return out

    def status(self) -> dict[str, Any]:
        cfg = self.config()
        return {**cfg, "has_key": self.has_key(cfg["exchange"]), "spent_today": round(self.spent_today(), 2),
                "withdrawals": self._state(f"withdrawals:{cfg['exchange']}") or None if cfg["exchange"] else None,
                "problems": self.problems(cfg), "problem_codes": [c for c, _ in self._problems(cfg)],
                "testnets": TESTNETS}

    # ------------------------------------------------------------------ proposals
    def _limit_problems(self, cfg: dict[str, Any], symbol: str, notional: float, exclude: str | None = None) -> list[str]:
        out = []
        if symbol not in cfg["symbols"]:
            out.append(f"{symbol} is not in your list of markets ({', '.join(cfg['symbols']) or 'empty'})")
        if notional > cfg["max_order"]:
            out.append(f"the order is worth about {notional:.2f}, above your per-order limit of {cfg['max_order']:.2f}")
        if self.spent_today() + notional > cfg["max_day"]:
            out.append(f"it would take today's real orders to {self.spent_today() + notional:.2f}, above your daily "
                       f"limit of {cfg['max_day']:.2f}")
        return out

    def propose(self, symbol: str, side: str, amount: float, est_price: float, type_: str = "market",
                price: float | None = None, conversation_id: str | None = None) -> dict[str, Any]:
        """A proposal the user can confirm in the app. Nothing is sent to the exchange here."""
        cfg = self.config()
        symbol = check_symbol(symbol)
        if side not in ("buy", "sell") or type_ not in ("market", "limit"):
            raise LiveError("side must be buy or sell, type market or limit")
        if not amount or amount <= 0 or est_price <= 0:
            raise LiveError("the amount and the price must be positive")
        if type_ == "limit" and (price is None or price <= 0):
            raise LiveError("a limit order needs a positive price")
        notional = amount * (price if type_ == "limit" and price else est_price)
        problems = self.problems(cfg) + self._limit_problems(cfg, symbol, notional)
        if problems:
            raise LiveError("; ".join(problems))
        order = {"id": uuid.uuid4().hex, "created": time.time(), "exchange": cfg["exchange"],
                 "sandbox": int(cfg["sandbox"]), "symbol": symbol, "side": side, "type": type_, "amount": float(amount),
                 "price": price, "est_price": float(est_price), "notional": round(notional, 2), "status": "proposed",
                 "decided": None, "result": "", "conversation_id": conversation_id}
        with self._lock:
            self._db.execute("INSERT INTO live_orders VALUES (:id,:created,:exchange,:sandbox,:symbol,:side,:type,"
                             ":amount,:price,:est_price,:notional,:status,:decided,:result,:conversation_id)", order)
            self._db.commit()
        return self.get(order["id"])

    def get(self, order_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM live_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise LiveError("no such order")
        order = dict(row)
        if order["status"] == "proposed" and time.time() - order["created"] > PROPOSAL_TTL_S:
            self._update(order_id, status="expired", decided=time.time())
            order["status"] = "expired"
        order["sandbox"] = bool(order["sandbox"])
        return order

    def orders(self, limit: int = 50) -> list[dict[str, Any]]:
        ids = [r["id"] for r in self._db.execute("SELECT id FROM live_orders ORDER BY created DESC LIMIT ?", (limit,))]
        return [self.get(i) for i in ids]

    def _update(self, order_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE live_orders SET {sets} WHERE id=?", (*fields.values(), order_id))
            self._db.commit()

    def cancel(self, order_id: str) -> dict[str, Any]:
        order = self.get(order_id)
        if order["status"] != "proposed":
            raise LiveError(f"this order is {order['status']}, not waiting for you")
        self._update(order_id, status="cancelled", decided=time.time())
        return self.get(order_id)

    def _exchange(self, cfg: dict[str, Any]) -> Any:
        k, s = key_names(cfg["exchange"])
        exchange = self.factory(cfg["exchange"], {"apiKey": self.secrets.get(k), "secret": self.secrets.get(s)})
        if cfg["sandbox"]:
            try:
                exchange.set_sandbox_mode(True)
            except Exception as exc:
                raise LiveError(f"{cfg['exchange']} has no test network in ccxt; turn test mode off to trade with "
                                "real funds") from exc
        return exchange

    async def confirm(self, order_id: str) -> dict[str, Any]:
        """The user's click: check everything again, then send this one order to the exchange."""
        order = self.get(order_id)
        if order["status"] != "proposed":
            raise LiveError(f"this order is {order['status']}, not waiting for you")
        cfg = self.config()
        problems = self.problems(cfg) + self._limit_problems(cfg, order["symbol"], order["notional"])
        if cfg["exchange"] != order["exchange"] or cfg["sandbox"] != order["sandbox"]:
            problems.append("the exchange settings changed since this order was proposed")
        if problems:
            raise LiveError("; ".join(problems))
        self._update(order_id, status="sending", decided=time.time())  # a second click cannot send it twice
        exchange = None
        try:
            exchange = self._exchange(cfg)
            placed = await exchange.create_order(order["symbol"], order["type"], order["side"], order["amount"],
                                                 order["price"] if order["type"] == "limit" else None)
        except Exception as exc:
            why = f"{exc.__class__.__name__}: {str(exc)[:300]}"
            self._update(order_id, status="failed", result=why)
            raise LiveError(f"the order was not confirmed by the exchange ({why}); if this was a network error, "
                            "check on the exchange whether it arrived before trying again") from exc
        finally:
            if exchange is not None:
                await exchange.close()
        result = (f"exchange order {placed.get('id')}: {placed.get('status') or 'sent'}"
                  + (f", filled {placed.get('filled')}" if placed.get("filled") is not None else "")
                  + (f" at {placed.get('average')}" if placed.get("average") else ""))
        self._update(order_id, status="placed", result=result[:400])
        return self.get(order_id)

    async def check_key(self) -> dict[str, Any]:
        """Try the key (a balance read) and, where the exchange tells, whether it may withdraw (Binance)."""
        cfg = self.config()
        if not cfg["exchange"] or not self.has_key(cfg["exchange"]):
            raise LiveError("save an API key for the chosen exchange first")
        exchange = self._exchange(cfg)
        withdrawals: bool | None = None
        try:
            await exchange.fetch_balance()
            # the test network has no such endpoint, and its funds are not real
            if cfg["exchange"] == "binance" and not cfg["sandbox"]:
                restrictions = await exchange.sapi_get_account_apirestrictions()
                withdrawals = bool(restrictions.get("enableWithdrawals"))
        except Exception as exc:
            raise LiveError(f"the key did not work: {exc.__class__.__name__}: {str(exc)[:200]}") from exc
        finally:
            await exchange.close()
        self._set_state(f"withdrawals:{cfg['exchange']}", "" if withdrawals is None else "yes" if withdrawals else "no")
        return {"ok": True, "withdrawals": withdrawals,
                "note": "" if withdrawals is not None else "test network: withdrawals not checked" if cfg["sandbox"]
                else "this exchange does not say whether the key can withdraw; check it on the exchange"}

    def close(self) -> None:
        self._db.close()
