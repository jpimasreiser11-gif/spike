"""Public market data: prices and candles from an exchange's public API through ccxt (MIT), without a key, kept
in a local cache so the same history is downloaded once; or candles from a CSV file the user has."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spike.finance.backtest import Candle

TIMEFRAMES = {"1h": 3600, "4h": 4 * 3600, "1d": 86400, "1w": 7 * 86400}
EXCHANGES = ["kraken", "binance", "coinbase", "bitstamp", "kucoin", "okx", "bybit"]
SYMBOL = re.compile(r"^[A-Z0-9]{1,15}/[A-Z0-9]{1,15}$")
MAX_DAYS = 3650
PAGE = 720  # candles per request: Kraken's limit, accepted by the others


class MarketError(Exception):
    pass


def check_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not SYMBOL.match(s):
        raise MarketError(f"'{symbol}' is not a market symbol like BTC/USDT or ETH/EUR")
    return s


def ccxt_exchange(exchange_id: str, config: dict[str, Any] | None = None) -> Any:
    """An async ccxt exchange (public calls need no key). ccxt is optional: `pip install 'spike-ai[finance]'`."""
    try:
        import ccxt.async_support as ccxt_async
    except ImportError as exc:
        raise MarketError("market data needs ccxt: pip install 'spike-ai[finance]'") from exc
    if exchange_id not in ccxt_async.exchanges:
        raise MarketError(f"unknown exchange '{exchange_id}'")
    return getattr(ccxt_async, exchange_id)({"enableRateLimit": True, "timeout": 20_000, **(config or {})})


def _error(exc: Exception) -> MarketError:
    name = exc.__class__.__name__
    if name in ("BadSymbol", "BadRequest"):
        return MarketError(f"the exchange does not list that market ({exc})")
    if name in ("NetworkError", "RequestTimeout", "ExchangeNotAvailable", "DDoSProtection", "RateLimitExceeded"):
        return MarketError(f"the exchange could not be reached: {name}")
    return MarketError(f"{name}: {str(exc)[:300]}")


class Market:
    def __init__(self, cache: Path, factory: Callable[[str], Any] = ccxt_exchange):
        cache.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS candles (exchange TEXT, symbol TEXT, timeframe TEXT, ts INTEGER, "
                         "o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (exchange, symbol, timeframe, ts))")
        self._db.commit()
        self._lock = threading.Lock()
        self.factory = factory

    async def _call(self, exchange_id: str, method: str, *args: Any) -> Any:
        exchange = self.factory(exchange_id)
        try:
            return await getattr(exchange, method)(*args)
        except MarketError:
            raise
        except Exception as exc:  # ccxt raises its own error classes
            raise _error(exc) from exc
        finally:
            await exchange.close()

    async def ticker(self, exchange_id: str, symbol: str) -> dict[str, Any]:
        symbol = check_symbol(symbol)
        t = await self._call(exchange_id, "fetch_ticker", symbol)
        last = t.get("last") or t.get("close")
        if last is None:
            raise MarketError(f"{exchange_id} gave no price for {symbol}")
        return {"exchange": exchange_id, "symbol": symbol, "last": float(last),
                "bid": t.get("bid"), "ask": t.get("ask"), "change_24h_pct": t.get("percentage"),
                "time_utc": datetime.fromtimestamp((t.get("timestamp") or time.time() * 1000) / 1000, UTC)
                .strftime("%Y-%m-%d %H:%M")}

    def _cached(self, exchange_id: str, symbol: str, timeframe: str, since: int) -> list[Candle]:
        with self._lock:
            rows = self._db.execute("SELECT ts, o, h, l, c, v FROM candles WHERE exchange=? AND symbol=? AND "
                                    "timeframe=? AND ts>=? ORDER BY ts", (exchange_id, symbol, timeframe, since))
            return [tuple(r) for r in rows.fetchall()]  # type: ignore[misc]

    async def ohlcv(self, exchange_id: str, symbol: str, timeframe: str = "1d", days: int = 365,
                    now_ms: int | None = None) -> list[Candle]:
        """Closed candles of the last `days`: what the cache lacks is downloaded page by page from the last one."""
        symbol = check_symbol(symbol)
        if timeframe not in TIMEFRAMES:
            raise MarketError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
        days = max(1, min(int(days), MAX_DAYS))
        step = TIMEFRAMES[timeframe] * 1000
        now = now_ms or int(time.time() * 1000)
        since = now - days * 86400 * 1000
        have = self._cached(exchange_id, symbol, timeframe, since)
        start = have[-1][0] + step if have and have[0][0] <= since + step else since
        exchange = self.factory(exchange_id)
        fetched: list[list[float]] = []
        try:
            while start <= now - step:
                page = await exchange.fetch_ohlcv(symbol, timeframe, start, PAGE)
                page = [c for c in page or [] if c[0] >= start]
                if not page:
                    break
                fetched += page
                start = int(page[-1][0]) + step
        except Exception as exc:
            if not have:
                raise _error(exc) from exc  # with a cache, an outage only means older numbers
        finally:
            await exchange.close()
        closed = [c for c in fetched if c[0] + step <= now and None not in c[:5]]  # the open candle still moves
        if closed:
            with self._lock:
                self._db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?)",
                                     [(exchange_id, symbol, timeframe, int(c[0]), float(c[1]), float(c[2]),
                                       float(c[3]), float(c[4]), float(c[5] or 0)) for c in closed])
                self._db.commit()
        return self._cached(exchange_id, symbol, timeframe, since)

    def close(self) -> None:
        self._db.close()


DATE_COLS = ("date", "time", "timestamp", "fecha", "datetime")


def _number(text: str) -> float:
    t = text.strip().replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)


def _stamp(text: str) -> int:
    t = text.strip()
    if re.fullmatch(r"\d{10,13}", t):
        n = int(t)
        return n if n > 10**11 else n * 1000
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y"):
        try:
            return int(datetime.strptime(t[:19], fmt).replace(tzinfo=UTC).timestamp() * 1000)
        except ValueError:
            continue
    raise MarketError(f"unreadable date '{text}' (use YYYY-MM-DD)")


def load_csv(text: str) -> list[Candle]:
    """Candles from a CSV with a date column and a close column (open/high/low/volume optional), sorted by date.
    Commas or semicolons; decimal comma accepted."""
    sample = text[:2000]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise MarketError("the CSV has no rows")
    cols = {k.strip().lower(): k for k in rows[0] if k}
    date = next((cols[c] for c in DATE_COLS if c in cols), None)
    close = next((cols[c] for c in ("close", "adj close", "cierre", "price", "precio") if c in cols), None)
    if not date or not close:
        raise MarketError("the CSV needs a date column and a close (or price) column")
    pick = {k: cols.get(k) for k in ("open", "high", "low", "volume")}
    out: dict[int, Candle] = {}
    for row in rows:
        try:
            c = _number(row[close])
            values = [(_number(row[pick[k]]) if pick[k] and row.get(pick[k], "").strip() else c)
                      for k in ("open", "high", "low")]
            vol = _number(row[pick["volume"]]) if pick["volume"] and row.get(pick["volume"], "").strip() else 0.0
            out[_stamp(row[date])] = (_stamp(row[date]), values[0], values[1], values[2], c, vol)
        except (ValueError, TypeError, KeyError):
            continue  # a blank or malformed line
    if len(out) < 2:
        raise MarketError("the CSV has fewer than 2 readable rows")
    return [out[k] for k in sorted(out)]
