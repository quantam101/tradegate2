"""Resilience tests: backoff, bounded retries, restart recovery."""

import asyncio
import io
import json
import time
import urllib.error
import urllib.request

import pytest

from runtime.tradegate.alpaca_broker import AlpacaPaperBroker
from runtime.tradegate.alpaca_feed import AlpacaTradeFeed
from runtime.tradegate.broker import Order, PaperBroker, load_ledger
from runtime.tradegate.events import Side, Strategy
from runtime.tradegate.resilience import Backoff, retry


# ── Backoff ──────────────────────────────────────────────────────────

def test_backoff_doubles_and_caps():
    import random
    bo = Backoff(base=10.0, cap=50.0, jitter=0.0, rng=random.Random(1))
    ds = [bo.next() for _ in range(4)]
    assert ds == pytest.approx([10.0, 20.0, 40.0, 50.0])


def test_backoff_resets_after_healthy_connection():
    import random
    bo = Backoff(base=10.0, cap=100.0, jitter=0.0, reset_after=60.0,
                 rng=random.Random(1))
    bo.next()
    bo.next()
    assert bo.next() == pytest.approx(40.0)
    bo.mark_connected()
    bo._connected_at -= 61.0  # connection lived past reset_after
    assert bo.next() == pytest.approx(10.0)
    assert bo.attempts == 1


def test_backoff_no_reset_for_short_connection():
    import random
    bo = Backoff(base=10.0, cap=100.0, jitter=0.0, reset_after=60.0,
                 rng=random.Random(1))
    bo.next()
    bo.mark_connected()  # dies immediately — still unhealthy
    assert bo.next() == pytest.approx(20.0)
    assert bo.attempts == 2


# ── retry ────────────────────────────────────────────────────────────

def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}
    sleeps = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("boom")
        return "ok"

    out = retry(flaky, AlpacaPaperBroker._retryable,
                attempts=3, sleep=sleeps.append)
    assert out == "ok" and calls["n"] == 3 and len(sleeps) == 2


def test_retry_does_not_retry_client_errors():
    calls = {"n": 0}

    def bad_request():
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b""))

    with pytest.raises(urllib.error.HTTPError):
        retry(bad_request, AlpacaPaperBroker._retryable,
              attempts=3, sleep=lambda s: None)
    assert calls["n"] == 1  # 400 is a client bug — fail fast


def test_retry_gives_up_after_attempts():
    def always_500():
        raise urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b""))

    with pytest.raises(urllib.error.HTTPError):
        retry(always_500, AlpacaPaperBroker._retryable,
              attempts=2, sleep=lambda s: None)


def test_http_429_is_retryable_4xx_is_not():
    assert AlpacaPaperBroker._retryable(
        urllib.error.HTTPError("u", 429, "rate", {}, io.BytesIO(b"")))
    assert AlpacaPaperBroker._retryable(
        urllib.error.HTTPError("u", 503, "down", {}, io.BytesIO(b"")))
    assert not AlpacaPaperBroker._retryable(
        urllib.error.HTTPError("u", 422, "bad", {}, io.BytesIO(b"")))


# ── AlpacaPaperBroker._req retry wiring ──────────────────────────────

class _Resp:
    def __init__(self, payload=b"{}"):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_alpaca_req_retries_transient_then_succeeds(monkeypatch):
    calls = {"n": 0}
    sleeps = []

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("conn reset")
        return _Resp(b'{"is_open": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    br = AlpacaPaperBroker(key="k", secret="s")
    assert br._req("GET", "/v2/clock") == {"is_open": True}
    assert calls["n"] == 2


def test_alpaca_req_404_returns_none_without_retry(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    br = AlpacaPaperBroker(key="k", secret="s")
    assert br._req("GET", "/v2/positions/X") is None
    assert calls["n"] == 1


# ── Restart recovery ─────────────────────────────────────────────────

def _fill_ledger(br: PaperBroker) -> None:
    asyncio.run(br.submit(Order("X", Side.BUY, Strategy.BETA_REVERSION,
                                100.0, 90.0, 110.0, 0, 30), 100.0))


def test_paper_broker_restores_fills_from_ledger(tmp_path):
    path = tmp_path / "fills.jsonl"
    b1 = PaperBroker(ledger_path=path, fee_bps=10.0)
    _fill_ledger(b1)
    assert len(b1.fills) == 1
    # simulate restart: new broker over same ledger
    b2 = PaperBroker(ledger_path=path)
    assert len(b2.fills) == 1
    assert b2.fills[0].side == Side.BUY
    assert b2.stats()["net_pnl"] == pytest.approx(b1.stats()["net_pnl"])


def test_load_ledger_skips_corrupt_lines(tmp_path):
    path = tmp_path / "fills.jsonl"
    b1 = PaperBroker(ledger_path=path)
    _fill_ledger(b1)
    with path.open("a") as f:
        f.write("{torn write at crash\n")
    fills = load_ledger(path)
    assert len(fills) == 1


def test_orchestrator_restores_equity_from_ledger(tmp_path):
    from runtime.tradegate.orchestrator import TradeGateOrchestrator
    path = tmp_path / "fills.jsonl"
    b1 = PaperBroker(ledger_path=path, fee_bps=10.0)
    _fill_ledger(b1)  # ENTRY fill with -fee pnl
    orch = TradeGateOrchestrator(initial_capital=1000.0, ledger_path=path)
    assert orch.equity == pytest.approx(1000.0 + b1.fills[0].pnl)
    # subsequent fills still accrue on top of restored equity
    before = orch.equity
    asyncio.run(orch.broker.submit(
        Order("Y", Side.BUY, Strategy.ALPHA_MOMENTUM, 50.0, 45.0, 60.0,
              0, 30), 50.0))
    assert orch.equity == pytest.approx(before + orch.broker.fills[-1].pnl)


def test_alpaca_broker_rehydrate_restores_positions(monkeypatch):
    br = AlpacaPaperBroker(key="k", secret="s")
    monkeypatch.setattr(br, "_req", lambda m, p, body=None, **kw: [
        {"symbol": "SPY", "qty": "3", "avg_entry_price": "500.00",
         "side": "long"},
        {"symbol": "QQQ", "qty": "1", "avg_entry_price": "400.00",
         "side": "long"},
    ] if p == "/v2/positions" else None)
    assert br.rehydrate() == 2
    pos = br.positions["SPY"]
    assert pos.qty == 3.0 and pos.entry_price == 500.0
    assert pos.strategy == Strategy.NONE


# ── Feed event callback + market clock ───────────────────────────────

def test_feed_event_callback_failure_never_raises():
    feed = AlpacaTradeFeed(["SPY"], key="k", secret="s",
                           on_event=lambda k, p: 1 / 0)
    feed._emit("FEED_CONNECTED")  # must not raise


def test_feed_market_clock_parsing(monkeypatch):
    feed = AlpacaTradeFeed(["SPY"], key="k", secret="s")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(b'{"is_open": true}'))
    assert feed.market_is_open() is True

    def boom(req, timeout=None):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert feed.market_is_open() is None  # unknown ≠ stalled
