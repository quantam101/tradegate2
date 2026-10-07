"""Tests for the real-data daily feed, Alpaca paper broker, and daily run."""
from __future__ import annotations

import json

import pytest

from runtime.tradegate.daily import run_daily
from runtime.tradegate.daily_feed import (
    DailyBarsFeed,
    bars_to_ticks,
    buy_hold_return,
    fetch_bars,
)
from runtime.tradegate.events import Tick


def _yahoo_payload(closes):
    n = len(closes)
    return json.dumps({
        "chart": {"result": [{
            "timestamp": [1700000000 + i * 86400 for i in range(n)],
            "indicators": {"quote": [{
                "open": closes, "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes], "close": closes,
                "volume": [1e6] * n,
            }]},
        }]}}).encode()


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_bars_yahoo(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Resp(_yahoo_payload([100, 101, 99, 103])))
    bars = fetch_bars("SPY")
    assert len(bars) == 4
    assert bars[-1].close == 103
    assert bars[0].high == 101.0


def test_fetch_bars_stooq_fallback(monkeypatch):
    csv_body = b"Date,Open,High,Low,Close,Volume\n2025-01-02,100,101,99,100.5,1000\n"
    calls = []

    def fake_urlopen(req, **kw):
        calls.append(req.full_url)
        if "yahoo" in req.full_url:
            raise OSError("yahoo down")
        return _Resp(csv_body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    bars = fetch_bars("SPY")
    assert len(calls) == 2 and "stooq.com" in calls[1]
    assert bars[0].close == 100.5


def test_bars_to_ticks_shape():
    from runtime.tradegate.daily_feed import Bar
    bars = [Bar(ts=1000 + i, open=10, high=11, low=9, close=10 + i * 0.25,
                volume=5e5) for i in range(3)]
    ticks = bars_to_ticks("SPY", bars)
    assert all(isinstance(t, Tick) for t in ticks)
    assert ticks[0].price == 10.0 and ticks[0].high == 11 and ticks[0].low == 9
    assert ticks[0].volume_delta == 5e5  # close > open → positive
    assert buy_hold_return(bars) == pytest.approx(0.05)


def test_daily_bars_feed_stream(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Resp(_yahoo_payload([10, 11, 12])))
    import asyncio
    feed = DailyBarsFeed("QQQ")

    async def collect():
        return [t async for t in feed.stream("QQQ")]

    ticks = asyncio.run(collect())
    assert len(ticks) == 3 and ticks[-1].price == 12


def test_run_daily_writes_ledger(monkeypatch, tmp_path):
    closes = [100 + i * 0.5 for i in range(60)]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Resp(_yahoo_payload(closes)))
    report = run_daily(["SPY", "QQQ"], capital=1000, ledger_dir=tmp_path)
    assert report["summary"]["symbols_ok"] == 2
    ledgers = list(tmp_path.glob("*.json"))
    assert len(ledgers) == 1
    stored = json.loads(ledgers[0].read_text())
    assert stored[0]["symbols"][0]["symbol"] == "SPY"
    assert "buy_hold_roi" in stored[0]["symbols"][0]


def test_run_daily_handles_fetch_failure(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    report = run_daily(["BAD"], ledger_dir=tmp_path)
    assert report["symbols"][0]["error"]
    assert report["summary"]["symbols_ok"] == 0


# ── Alpaca paper broker ────────────────────────────────────────────────

def test_alpaca_requires_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET", raising=False)
    from runtime.tradegate.alpaca_broker import AlpacaPaperBroker
    with pytest.raises(ValueError):
        AlpacaPaperBroker()


def test_alpaca_submit_bracket(monkeypatch):
    from runtime.tradegate.alpaca_broker import AlpacaPaperBroker
    from runtime.tradegate.broker import Order
    from runtime.tradegate.events import Side, Strategy

    posted = {}

    class Br:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, **kw):
        if req.get_method() == "POST" and req.full_url.endswith("/v2/orders"):
            posted.update(json.loads(req.data))
            return Br(b'{"id": "abc123"}')
        return Br(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    b = AlpacaPaperBroker(key="k", secret="s")
    order = Order(symbol="SPY", side=Side.BUY, strategy=Strategy.ALPHA_MOMENTUM,
                  capital=1000, stop_price=95.0, take_profit=110.0,
                  placed_ts=1.0, expires_ts=31.0)
    import asyncio
    fill = asyncio.run(b.submit(order, ref_price=100.0))
    assert fill and fill.kind == "ENTRY"
    assert posted["order_class"] == "bracket"
    assert posted["take_profit"]["limit_price"] == "110.00"
    assert posted["stop_loss"]["stop_price"] == "95.00"
    assert posted["type"] == "market" and posted["time_in_force"] == "day"
    assert b.positions["SPY"].qty == 10


def test_alpaca_on_tick_detects_bracket_exit(monkeypatch):
    from runtime.tradegate.alpaca_broker import AlpacaPaperBroker
    from runtime.tradegate.broker import Order
    from runtime.tradegate.events import Side, Strategy, Tick

    class Br:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, **kw):
        url = req.full_url
        if req.get_method() == "POST":
            return Br(b'{"id": "abc"}')
        if "/v2/positions/SPY" in url:
            if req.get_method() == "GET":
                import urllib.error
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            return Br(b"{}")
        if "/v2/orders" in url:
            return Br(json.dumps([{"side": "sell", "filled_avg_price": "109.50"}]).encode())
        return Br(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    b = AlpacaPaperBroker(key="k", secret="s")
    order = Order(symbol="SPY", side=Side.BUY, strategy=Strategy.BETA_REVERSION,
                  capital=500, stop_price=95.0, take_profit=110.0,
                  placed_ts=1.0, expires_ts=31.0)
    import asyncio
    asyncio.run(b.submit(order, 100.0))
    tick = Tick(symbol="SPY", timestamp=2.0, price=109.0, bid=109, ask=109.1,
                bids_depth=1, asks_depth=1, volume_delta=0, high=110, low=108)
    exits = asyncio.run(b.on_tick(tick))
    assert len(exits) == 1 and exits[0].kind == "EXIT_BRACKET"
    # honest fill price from the closed leg, not the tick price
    assert exits[0].price == 109.50
    assert exits[0].pnl == pytest.approx((109.50 - 100.0) * 5)
    assert "SPY" not in b.positions
