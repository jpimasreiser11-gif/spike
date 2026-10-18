"""Spike Finance (C5): metrics, backtests and risk against hand-computed values, the market cache, the paper
account, and real orders: off by default, only proposed by a model, placed only by the user's click, within limits."""

import json
import math
import statistics
import time

import pytest
from fastapi.testclient import TestClient

from spike.finance import live as live_trading
from spike.finance.analysis import max_drawdown, metrics, portfolio_risk
from spike.finance.backtest import rsi, run_backtest, sma
from spike.finance.live import LiveError, LiveTrading
from spike.finance.market import Market, MarketError, load_csv
from spike.finance.paper import PaperAccount, PaperError
from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.secrets import SecretStore
from tests.helpers import ScriptedProvider, call, text

DAY = 86_400_000


class NetworkError(Exception):  # named like ccxt's, which Market maps by class name
    pass


class FakeExchange:
    """Stands in for a ccxt async exchange: daily candles 0..`last` (close = 100 + index), a fixed ticker."""

    def __init__(self, book: dict, exchange_id: str, config: dict | None):
        self.book, self.id, self.config = book, exchange_id, config or {}
        book["made"].append((exchange_id, self.config))

    def set_sandbox_mode(self, on: bool) -> None:
        if self.id not in live_trading.TESTNETS:
            raise TypeError("no test url")
        self.book["sandbox"].append(on)

    async def fetch_ticker(self, symbol):
        if self.book.get("down"):
            raise NetworkError("offline")
        return {"last": self.book["prices"].get(symbol, 50_000.0), "bid": None, "ask": None, "percentage": 1.5,
                "timestamp": 0}

    async def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.book["ohlcv"].append((symbol, timeframe, since, limit))
        if self.book.get("down"):
            raise NetworkError("offline")
        first = max(0, math.ceil(since / DAY))
        return [[k * DAY, 100.0 + k, 101.0 + k, 99.0 + k, 100.0 + k, 1.0]
                for k in range(first, min(first + limit, self.book["last"] + 1))]

    async def create_order(self, symbol, type_, side, amount, price=None):
        self.book["orders"].append((symbol, type_, side, amount, price))
        if self.book.get("refuse"):
            raise NetworkError("timeout")
        return {"id": "X1", "status": "closed", "filled": amount, "average": 50_010.0}

    async def fetch_balance(self):
        return {"total": {}}

    async def sapi_get_account_apirestrictions(self):
        return {"enableWithdrawals": self.book.get("withdrawals", False)}

    async def close(self):
        self.book["closed"] += 1


@pytest.fixture
def book():
    return {"made": [], "sandbox": [], "ohlcv": [], "orders": [], "closed": 0, "prices": {}, "last": 0}


def factory_for(book):
    return lambda exchange_id, config=None: FakeExchange(book, exchange_id, config)


# ---------------------------------------------------------------- numbers, checked by hand
def test_metrics_match_hand_computed_values():
    m = metrics([100, 110, 99, 121], 365)
    r = [0.1, -0.1, 121 / 99 - 1]
    assert m["total_return"] == pytest.approx(0.21)
    assert m["max_drawdown"] == pytest.approx(-0.1)  # 110 → 99
    assert m["volatility"] == pytest.approx(statistics.stdev(r) * math.sqrt(365), rel=1e-5)
    assert m["sharpe"] == pytest.approx(statistics.mean(r) / statistics.stdev(r) * math.sqrt(365), rel=1e-4)
    assert m["cagr"] == pytest.approx(1.21 ** (365 / 3) - 1, rel=1e-5)
    assert max_drawdown([1, 2, 1, 3, 1.5]) == pytest.approx(-0.5)
    assert metrics([100], 365)["sharpe"] is None


def test_indicators_match_hand_computed_values():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    # gains 1,1,0,0 and losses 0,0,1,1; Wilder's smoothing with n=2 gives 100, then 50, then 25
    assert rsi([1, 2, 3, 2, 1], 2) == [None, None, 100.0, 50.0, 25.0]


def test_buy_and_hold_pays_the_fee_and_trades_at_the_next_open():
    candles = [(0, 100, 100, 100, 100, 0), (DAY, 100, 110, 100, 110, 0), (2 * DAY, 110, 121, 110, 121, 0)]
    r = run_backtest(candles, "buy_hold", fee=0.001, slippage=0, cash=1000)
    # bought at bar 1's open: (1000 − 1 fee) / 100 = 9.99 units, worth 9.99 × 121 at the end
    assert r["final_equity"] == 1208.79 and r["trades"] == 1 and r["round_trips"] == 0
    assert r["last_trades"][0]["t"] == DAY and r["last_trades"][0]["price"] == 100
    assert r["exposure"] == pytest.approx(2 / 3, abs=1e-4) and r["win_rate"] is None
    assert "Past results do not predict" in r["note"]


def test_sma_cross_never_uses_a_price_it_could_not_know():
    closes, opens = [10, 12, 11, 9, 10, 13], [10, 10, 12, 11, 9, 10]
    candles = [(i * DAY, o, max(o, c), min(o, c), c, 0) for i, (o, c) in enumerate(zip(opens, closes, strict=True))]
    r = run_backtest(candles, "sma_cross", {"fast": 1, "slow": 2}, fee=0, slippage=0, cash=100)
    # the cross at bar 1's close buys at bar 2's open (12); out at bar 3's open (11); in again at bar 5's open (10)
    trades = [(t["t"] // DAY, t["side"], t["price"]) for t in r["last_trades"]]
    assert trades == [(2, "buy", 12), (3, "sell", 11), (5, "buy", 10)]
    assert r["final_equity"] == round(100 / 12 * 11 / 10 * 13, 2) == 119.17
    assert r["round_trips"] == 1 and r["win_rate"] == 0 and r["exposure"] == pytest.approx(2 / 6, abs=1e-4)
    with pytest.raises(ValueError, match="fast < slow"):
        run_backtest(candles, "sma_cross", {"fast": 3, "slow": 2})
    with pytest.raises(ValueError, match="too few"):
        run_backtest(candles[:3], "sma_cross", {"fast": 1, "slow": 2})


def test_portfolio_risk_matches_hand_computed_values():
    a = [(0, 100), (DAY, 110), (2 * DAY, 99), (3 * DAY, 108.9)]  # +10 %, −10 %, +10 %
    b = [(0, 50), (DAY, 50), (2 * DAY, 55), (3 * DAY, 55), (4 * DAY, 60)]  # 0, +10 %, 0; the last day only B has
    r = portfolio_risk({"A": a, "B": b}, {"A": 1, "B": 1}, 1)
    assert r["observations"] == 3 and r["weights"] == {"A": 0.5, "B": 0.5}
    # portfolio returns 5 %, 0 %, 5 %: sample std √(0.0025/3) = 0.028868
    assert r["volatility"] == pytest.approx(0.028868, abs=1e-6)
    assert r["total_return"] == pytest.approx(1.05 * 1.0 * 1.05 - 1)
    assert r["var"] == pytest.approx(-0.005) and r["expected_shortfall"] == 0  # no losing day in this sample
    assert r["correlation"]["A"]["B"] == pytest.approx(-1.0)
    assert r["risk_share"] == pytest.approx({"A": 2.0, "B": -1.0})  # B hedges A: shares add up to 1
    with pytest.raises(ValueError, match="fewer than 3"):
        portfolio_risk({"A": a[:2]}, {"A": 1}, 1)


def test_csv_prices_with_semicolons_and_decimal_commas():
    rows = load_csv("fecha;cierre\n2024-01-02;1.010,25\n2024-01-01;1.000,5\n;\n")
    assert [r[4] for r in rows] == [1000.5, 1010.25] and rows[0][0] == 1704067200000
    rows = load_csv("timestamp,open,high,low,close,volume\n1704067200,1,2,0.5,1.5,10\n1704153600000,1.5,2,1,2,5\n")
    assert rows[1] == (1704153600000, 1.5, 2.0, 1.0, 2.0, 5.0)
    with pytest.raises(MarketError, match="date column"):
        load_csv("a,b\n1,2\n3,4\n")


# ---------------------------------------------------------------- market data
async def test_history_is_downloaded_once_by_pages_and_never_includes_the_open_candle(tmp_path, book):
    book["last"] = 2000
    market = Market(tmp_path / "m.db", factory_for(book))
    now = 2000 * DAY + 3_600_000  # an hour into day 2000: that candle is still open
    data = await market.ohlcv("kraken", "btc/usdt", "1d", 1000, now)
    assert len(data) == 999 and data[0][0] == 1001 * DAY and data[-1][0] == 1999 * DAY
    assert [c[3] for c in book["ohlcv"]] == [720, 720]  # two pages
    again = await market.ohlcv("kraken", "BTC/USDT", "1d", 1000, now)
    assert again == data and len(book["ohlcv"]) == 2  # all from the cache
    book["down"] = True
    assert await market.ohlcv("kraken", "BTC/USDT", "1d", 1000, now + DAY) == data[1:]  # an outage: older numbers
    with pytest.raises(MarketError, match="could not be reached"):
        await market.ohlcv("kraken", "ETH/USDT", "1d", 10, now)
    with pytest.raises(MarketError, match="not a market symbol"):
        await market.ohlcv("kraken", "BTC-USDT", "1d", 10, now)
    assert book["closed"] == len(book["made"])  # every exchange object is closed


# ---------------------------------------------------------------- paper account
def test_paper_trading_charges_fees_and_slippage(tmp_path):
    paper = PaperAccount(tmp_path / "p.db")
    paper.reset(1000, "usdt")
    buy = paper.place("kraken", "BTC/USDT", "buy", 0.01, 50_000)
    assert buy["status"] == "filled" and buy["fill_price"] == pytest.approx(50_025)  # +0.05 % slippage
    assert paper.state()["balances"] == pytest.approx({"USDT": 1000 - 500.25 - 0.50025, "BTC": 0.01})
    paper.place("kraken", "BTC/USDT", "sell", 0.005, 60_000)  # filled at 59 970, fee 0.29985
    v = paper.valuation({"BTC/USDT": 60_000})
    assert v["total"] == pytest.approx(round(499.24975 + 299.85 - 0.29985 + 300, 2)) and v["pnl"] == 98.8
    with pytest.raises(PaperError, match="not enough USDT"):
        paper.place("kraken", "BTC/USDT", "buy", 1, 60_000)
    with pytest.raises(PaperError, match="not enough BTC"):
        paper.place("kraken", "BTC/USDT", "sell", 1, 60_000)
    limit = paper.place("kraken", "BTC/USDT", "buy", 0.001, 50_000, "limit", 40_000)
    assert limit["status"] == "open" and paper.refresh({"BTC/USDT": 45_000}) == []
    filled = paper.refresh({"BTC/USDT": 39_000})
    assert filled[0]["fill_price"] == 40_000 and filled[0]["fee"] == pytest.approx(0.04)  # its price, no slippage
    waiting = paper.place("kraken", "BTC/USDT", "sell", 0.001, 50_000, "limit", 70_000)
    assert paper.cancel(waiting["id"])["status"] == "cancelled"
    with pytest.raises(PaperError):
        paper.cancel(waiting["id"])
    assert paper.valuation({})["unpriced"] == ["BTC"] and paper.valuation({})["pnl"] is None


# ---------------------------------------------------------------- real orders
def make_live(tmp_path, book, **cfg):
    settings = {"live": live_trading.clean(cfg) if cfg else dict(live_trading.DEFAULTS)}
    live = LiveTrading(tmp_path / "live.db", SecretStore(tmp_path / "secrets.json"), lambda: settings["live"],
                       factory_for(book))
    return live, settings


ON = {"enabled": True, "exchange": "binance", "no_withdrawal": True, "symbols": ["btc/usdt"], "max_order": 100,
      "max_day": 150}


def test_real_orders_are_off_by_default_and_need_every_safeguard(tmp_path, book, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    live, _ = make_live(tmp_path, book)
    status = live.status()
    assert status["enabled"] is False and status["sandbox"] is True and "real orders are off" in status["problems"][0]
    with pytest.raises(LiveError, match="real orders are off"):
        live.propose("BTC/USDT", "buy", 0.001, 50_000)
    with pytest.raises(ValueError, match="cannot withdraw"):
        live_trading.clean({**ON, "no_withdrawal": False})
    with pytest.raises(ValueError, match="per-order limit"):
        live_trading.clean({**ON, "max_order": 500})
    with pytest.raises(ValueError, match="unknown"):
        live_trading.clean({"auto": True})
    live, settings = make_live(tmp_path / "2", book, **ON)
    assert "no API key saved for binance" in live.problems()
    live.set_key("binance", "KEY", "SECRET")
    assert live.problems() == []
    settings["live"] = live_trading.clean({**ON, "exchange": "kraken"})
    live.set_key("kraken", "K", "S")
    assert any("no test network" in p for p in live.problems())  # test mode on an exchange without one
    assert book["made"] == []  # nothing so far talked to an exchange


async def test_a_proposal_is_placed_only_when_confirmed_and_within_limits(tmp_path, book, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    live, _ = make_live(tmp_path, book, **ON)
    live.set_key("binance", "KEY", "SECRET")
    order = live.propose("BTC/USDT", "buy", 0.001, 50_000)
    assert order["status"] == "proposed" and order["notional"] == 50 and order["sandbox"] is True
    assert book["orders"] == []  # proposing sends nothing
    with pytest.raises(LiveError, match="per-order limit"):
        live.propose("BTC/USDT", "buy", 0.01, 50_000)
    with pytest.raises(LiveError, match="not in your list"):
        live.propose("ETH/USDT", "buy", 0.01, 3000)
    placed = await live.confirm(order["id"])
    assert placed["status"] == "placed" and "X1" in placed["result"]
    assert book["orders"] == [("BTC/USDT", "market", "buy", 0.001, None)] and book["sandbox"] == [True]
    assert book["made"][-1] == ("binance", {"apiKey": "KEY", "secret": "SECRET"})
    with pytest.raises(LiveError, match="placed"):
        await live.confirm(order["id"])  # a second click sends nothing
    assert len(book["orders"]) == 1
    second = live.propose("BTC/USDT", "buy", 0.0019, 50_000)  # 95: 145 today, under 150
    await live.confirm(second["id"])
    with pytest.raises(LiveError, match="daily limit"):
        live.propose("BTC/USDT", "buy", 0.0002, 50_000)  # 10 more: 155
    assert live.spent_today() == 145


async def test_proposals_expire_can_be_cancelled_and_failures_are_kept(tmp_path, book, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    live, settings = make_live(tmp_path, book, **ON)
    live.set_key("binance", "KEY", "SECRET")
    old = live.propose("BTC/USDT", "buy", 0.001, 50_000)
    live._update(old["id"], created=time.time() - live_trading.PROPOSAL_TTL_S - 1)
    assert live.get(old["id"])["status"] == "expired"
    with pytest.raises(LiveError, match="expired"):
        await live.confirm(old["id"])
    cancelled = live.propose("BTC/USDT", "sell", 0.001, 50_000)
    assert live.cancel(cancelled["id"])["status"] == "cancelled"
    changed = live.propose("BTC/USDT", "buy", 0.001, 50_000)
    settings["live"] = live_trading.clean({**ON, "sandbox": False})
    with pytest.raises(LiveError, match="settings changed"):
        await live.confirm(changed["id"])  # proposed for the test network, not for real funds
    settings["live"] = live_trading.clean(ON)
    book["refuse"] = True
    failing = live.propose("BTC/USDT", "buy", 0.001, 50_000)
    with pytest.raises(LiveError, match="check on the exchange"):
        await live.confirm(failing["id"])
    assert live.get(failing["id"])["status"] == "failed" and book["orders"] and book["closed"] == len(book["made"])
    book["refuse"] = False
    waiting = live.propose("BTC/USDT", "buy", 0.001, 50_000)
    settings["live"] = live_trading.clean({**ON, "enabled": False})
    with pytest.raises(LiveError, match="real orders are off"):
        await live.confirm(waiting["id"])  # turned off after it was proposed: nothing is sent
    assert len(book["orders"]) == 1


async def test_the_key_check_reports_withdrawal_rights(tmp_path, book, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    live, _ = make_live(tmp_path, book, **{**ON, "sandbox": False})
    live.set_key("binance", "KEY", "SECRET")
    book["withdrawals"] = True
    assert (await live.check_key())["withdrawals"] is True
    assert any("can withdraw" in p for p in live.problems())
    with pytest.raises(LiveError, match="can withdraw"):
        live.propose("BTC/USDT", "buy", 0.001, 50_000)
    book["withdrawals"] = False
    assert (await live.check_key())["withdrawals"] is False and live.problems() == []
    live2, _ = make_live(tmp_path / "t", book, **ON)
    live2.set_key("binance", "KEY", "SECRET")
    assert (await live2.check_key())["note"].startswith("test network")


# ---------------------------------------------------------------- the app
@pytest.fixture
def env(tmp_path, monkeypatch, book):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory, market_factory=factory_for(book))
    app = create_app(state)
    return TestClient(app, client=("127.0.0.1", 50_000)), TestClient(app), local, state


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_api_sets_up_real_orders_only_from_this_computer(env, book):
    client, remote, _, state = env
    info = client.get("/api/finance").json()
    assert info["live"]["enabled"] is False and info["settings"]["exchange"] == "kraken"
    assert "binance" in info["exchanges"] and "sma_cross" in info["strategies"]
    live = {"live": ON}
    assert remote.put("/api/settings", json={"finance": live}).status_code == 403  # another machine
    assert remote.put("/api/finance/live/key", json={"exchange": "binance", "api_key": "K", "secret": "S"}
                      ).status_code == 403
    assert client.put("/api/settings", json={"finance": live}, headers={"origin": "https://evil.example"}
                      ).status_code == 403
    bad = client.put("/api/settings", json={"finance": {"live": {"enabled": True}}})
    assert bad.status_code == 400 and "cannot withdraw" in bad.json()["detail"]
    assert client.put("/api/settings", json={"finance": live}).json()["finance"]["live"]["enabled"] is True
    assert client.put("/api/settings", json={"finance": {"live": {"max_day": 200}}}
                      ).json()["finance"]["live"]["symbols"] == ["BTC/USDT"]  # a partial change keeps the rest
    status = client.put("/api/finance/live/key", json={"exchange": "binance", "api_key": "THE-KEY",
                                                       "secret": "THE-SECRET"}).json()
    assert status["has_key"] is True and status["problems"] == []
    for url in ("/api/finance", "/api/settings"):
        assert "THE-SECRET" not in client.get(url).text and "THE-KEY" not in client.get(url).text
    assert "THE-SECRET" not in (state.home / "spike.db").read_bytes().decode("latin-1")
    assert client.post("/api/finance/live/check").json()["ok"] is True

    order = state.finance.live.propose("BTC/USDT", "buy", 0.001, 50_000)
    url = f"/api/finance/live/orders/{order['id']}/confirm"
    assert client.post(url, json={"id": order["id"]}).status_code == 400  # no header
    assert remote.post(url, json={"id": order["id"]}, headers={"x-spike-confirm": order["id"]}).status_code == 403
    assert client.post(url, json={"id": order["id"]}, headers={"x-spike-confirm": order["id"],
                                                               "origin": "https://evil.example"}).status_code == 403
    assert book["orders"] == []
    placed = client.post(url, json={"id": order["id"]}, headers={"x-spike-confirm": order["id"]}).json()
    assert placed["status"] == "placed" and len(book["orders"]) == 1
    again = client.post(url, json={"id": order["id"]}, headers={"x-spike-confirm": order["id"]})
    assert again.status_code == 409 and len(book["orders"]) == 1
    other = state.finance.live.propose("BTC/USDT", "sell", 0.001, 50_000)
    assert client.post(f"/api/finance/live/orders/{other['id']}/cancel").json()["status"] == "cancelled"
    assert [o["status"] for o in client.get("/api/finance/live/orders").json()] == ["cancelled", "placed"]
    assert client.delete("/api/finance/live/key/binance").json()["has_key"] is False


def test_the_paper_account_api(env, book):
    client, _, local, _ = env
    assert client.post("/api/finance/paper/reset", json={"cash": 500, "quote": "eur"}).json()["valuation"][
        "total"] == 500
    assert client.post("/api/finance/paper/reset", json={"cash": -1}).status_code == 422
    client.post("/api/finance/paper/reset", json={"cash": 1000})
    book["prices"]["BTC/USDT"] = 50_000.0
    local._script = [call("paper_order", {"symbol": "BTC/USDT", "side": "buy", "amount": 0.01}), text("ok")]
    client.post("/api/chat", json={"message": "compra en paper", "mode": "finance"})
    view = client.get("/api/finance/paper").json()
    assert view["balances"]["BTC"] == 0.01 and view["price_error"] is None
    assert view["valuation"]["total"] == pytest.approx(1000 - 0.50025 - 500.25 + 500, abs=0.01)
    assert view["orders"][0]["status"] == "filled"
    book["down"] = True
    offline = client.get("/api/finance/paper").json()
    assert offline["price_error"] and offline["valuation"]["unpriced"] == ["BTC"]


def test_a_specialist_proposes_and_the_chat_shows_the_order_card(env, book):
    client, _, local, state = env
    client.put("/api/settings", json={"finance": {"live": ON}})
    state.finance.live.set_key("binance", "KEY", "SECRET")
    book["prices"]["BTC/USDT"] = 50_000.0
    local._script = [call("propose_live_order", {"symbol": "BTC/USDT", "side": "buy", "amount": 0.001}),
                     text("Te he propuesto la orden; confírmala en la tarjeta.")]
    r = client.post("/api/chat", json={"message": "Compra 0.001 BTC de verdad", "mode": "finance"})
    result = next(e for e in events_of(r) if e["type"] == "tool_result")
    assert result["ok"] and result["ui"]["kind"] == "live_order" and "NOT placed" in result["content"]
    assert result["ui"]["order"]["status"] == "proposed" and result["ui"]["order"]["notional"] == 50
    assert book["orders"] == []  # the model could only propose it
    names = {t.name for t in local.requests[0].tools}
    assert {"propose_live_order", "paper_order", "backtest", "portfolio_risk"} <= names


def test_callers_with_no_one_to_confirm_never_get_the_real_order_tool(env):
    client, _, local, _ = env
    local._script = lambda req: text("ok")
    r = client.post("/v1/chat/completions", json={"model": "spike-finance",
                                                  "messages": [{"role": "user", "content": "compra BTC"}]})
    assert r.status_code == 200, r.text
    names = {t.name for t in local.requests[-1].tools}
    assert "paper_order" in names and "propose_live_order" not in names and "ask_user" not in names


def test_finance_tools_answer_from_market_data(env, book):
    client, _, local, _ = env
    book["last"] = int(time.time() * 1000) // DAY  # daily candles up to today
    local._script = [call("backtest", {"symbol": "BTC/USDT", "strategy": "buy_hold", "days": 30}),
                     text("hecho")]
    r = client.post("/api/chat", json={"message": "backtest", "mode": "finance"})
    result = next(e for e in events_of(r) if e["type"] == "tool_result")
    data = json.loads(result["content"])
    assert result["ok"] and data["strategy"] == "buy_hold" and data["market"] == "BTC/USDT on kraken"
    assert data["buy_hold"]["total_return"] == data["total_return"]
