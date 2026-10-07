"""Governance-layer tests: vetoes, consensus, latency degrade, kill-switch,
sentiment scoring, and the process-per-agent mesh."""
from __future__ import annotations

import asyncio
import time

from runtime.tradegate.agents import ExecutionAgent, RiskAgent, SentimentAgent
from runtime.tradegate.broker import PaperBroker
from runtime.tradegate.config import ConfigStore, EngineConfig
from runtime.tradegate.events import MarketEvent, Side, Signal, Strategy, Tick
from runtime.tradegate.sentiment import load, refresh, score_headlines


def _evt(price=100.0, bid=99.9, ask=100.1, votes=None, sentiment=0.0,
         sized=0.0):
    t = Tick(symbol="SPY", timestamp=time.time(), price=price, bid=bid,
             ask=ask, bids_depth=1e5, asks_depth=1e5, volume_delta=1,
             high=price * 1.001, low=price * 0.999)
    e = MarketEvent(tick=t, event_id="t")
    e.signal = Signal(Side.BUY, Strategy.ALPHA_MOMENTUM, "t")
    e.votes = votes or []
    e.sentiment = sentiment
    e.atr = 1.0
    return e


async def _drive(risk, events, q_out):
    for e in events:
        await risk.q_in.put(e)
    await risk.q_in.put(None)
    await asyncio.gather(asyncio.create_task(risk.run()), return_exceptions=True)
    out = []
    while not q_out.empty():
        item = await q_out.get()
        if item is not None:
            out.append(item)
    return out


def _risk(store, equity=1000.0, on_halt=None):
    q_in, q_out = asyncio.Queue(), asyncio.Queue()
    return RiskAgent(q_in, q_out, store, lambda: equity, on_halt=on_halt), q_in, q_out


def test_sentiment_lexicon_direction():
    assert score_headlines(["market rally as stocks surge on beat expectations"]) > 0
    assert score_headlines(["crash fears grow amid recession warnings, selloff"]) < 0
    assert score_headlines(["the meeting happened on tuesday"]) == 0.0


def test_sentiment_refresh_writes_and_loads(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.tradegate.sentiment._llm_score", lambda h: None)
    p = tmp_path / "s.json"
    doc = refresh(["stocks surge on record profits"], p)
    assert doc["method"] == "lexicon" and doc["score"] > 0
    assert load(p) == doc["score"]
    assert load(tmp_path / "missing.json") == 0.0


def test_sentiment_agent_stamps_and_votes(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.tradegate.sentiment._llm_score", lambda h: None)
    p = tmp_path / "s.json"
    refresh(["bankruptcy, crash, selloff, recession, default, probe"], p)
    q_in, q_out = asyncio.Queue(), asyncio.Queue()
    agent = SentimentAgent(q_in, q_out, path=p)

    async def go():
        e = _evt()
        await q_in.put(e)
        await q_in.put(None)
        await asyncio.gather(asyncio.create_task(agent.run()),
                             return_exceptions=True)
        return await q_out.get()

    evt = asyncio.run(go())
    assert evt.sentiment < -0.5
    assert evt.votes[0]["agent"] == "sentiment" and evt.votes[0]["side"] == "SELL"


def test_risk_sentiment_veto():
    store = ConfigStore()
    risk, _qin, q_out = _risk(store)
    e = _evt(sentiment=-0.8)
    out = asyncio.run(_drive(risk, [e], q_out))
    assert risk.vetoes["sentiment"] == 1
    assert out == []


def test_risk_slippage_guard():
    store = ConfigStore()
    risk, _qin, q_out = _risk(store)
    # price 12% away from mid — beyond the 40bps cap
    e = _evt(price=110.0, bid=99.9, ask=100.1)
    out = asyncio.run(_drive(risk, [e], q_out))
    assert risk.vetoes["slippage"] == 1
    assert out == []


def test_consensus_quorum_blocks_big_orders():
    cfg = EngineConfig(consensus_threshold_usd=10.0, consensus_min_votes=3,
                       consensus_min_score=0.82, rolling_win_rate=0.9,
                       rolling_payout_ratio=2.0, max_trade_fraction=0.9)
    store = ConfigStore()
    store.swap(**cfg.to_dict())
    risk, _qin, q_out = _risk(store)
    # only 2 confident votes — below the 3-vote quorum
    e = _evt(votes=[{"agent": "a", "side": "BUY", "confidence": 0.9},
                    {"agent": "b", "side": "BUY", "confidence": 0.5}])
    out = asyncio.run(_drive(risk, [e], q_out))
    assert risk.vetoes["consensus"] == 1
    assert out == []


def test_consensus_quorum_passes_with_votes():
    cfg = EngineConfig(consensus_threshold_usd=10.0, consensus_min_votes=3,
                       consensus_min_score=0.5, rolling_win_rate=0.9,
                       rolling_payout_ratio=2.0, max_trade_fraction=0.9)
    store = ConfigStore()
    store.swap(**cfg.to_dict())
    risk, _qin, q_out = _risk(store)
    e = _evt(votes=[{"agent": a, "side": "BUY", "confidence": 0.9}
                    for a in ("regime", "alpha", "sentiment")])
    out = asyncio.run(_drive(risk, [e], q_out))
    assert risk.vetoes["consensus"] == 0
    assert len(out) == 1


def test_notional_cap():
    cfg = EngineConfig(max_notional_usd=50.0, rolling_win_rate=0.9,
                       rolling_payout_ratio=2.0, max_trade_fraction=1.0,
                       consensus_threshold_usd=1e9)
    store = ConfigStore()
    store.swap(**cfg.to_dict())
    risk, _qin, q_out = _risk(store, equity=10_000_000)
    e = _evt()
    out = asyncio.run(_drive(risk, [e], q_out))
    assert out[0].sized_capital == 50.0  # capped at fat-finger limit


def test_killswitch_flattens_and_cancels():
    store = ConfigStore()
    broker = PaperBroker()

    # equity drops 50% vs the peak — drawdown breaker trips on event 2
    equity_seq = iter([1000.0, 500.0])
    risk, _qin, q_out = _risk(store, equity=0.0)
    risk.equity_ref = lambda: next(equity_seq)
    out = asyncio.run(_drive(risk, [_evt(), _evt()], q_out))
    assert risk.halted
    assert len(out) == 2                     # first sized, second is halt
    assert out[1].halt is True

    # the halt event travels the mesh — ExecutionAgent flattens + marker
    q_in2, q_out2 = asyncio.Queue(), asyncio.Queue()
    ex = ExecutionAgent(q_in2, q_out2, broker, store)

    async def go():
        await q_in2.put(out[1])
        await q_in2.put(None)
        await asyncio.gather(asyncio.create_task(ex.run()),
                             return_exceptions=True)
        got = []
        while not q_out2.empty():
            item = await q_out2.get()
            if item is not None:
                got.append(item)
        return got

    got = asyncio.run(go())
    # no open positions → only the KILL_SWITCH marker (evt, None)
    assert got and got[0][1] is None
    assert "KILL_SWITCH" in got[0][0].signal.reason


def test_quorum_ignores_opposing_votes():
    """Confident SELL votes must never approve a large BUY order."""
    cfg = EngineConfig(consensus_threshold_usd=10.0, consensus_min_votes=3,
                       consensus_min_score=0.5, rolling_win_rate=0.9,
                       rolling_payout_ratio=2.0, max_trade_fraction=0.9)
    store = ConfigStore()
    store.swap(**cfg.to_dict())
    risk, _qin, q_out = _risk(store)
    e = _evt(votes=[{"agent": a, "side": "SELL", "confidence": 0.99}
                    for a in ("x", "y", "z")])
    out = asyncio.run(_drive(risk, [e], q_out))
    assert risk.vetoes["consensus"] == 1
    assert out == []


def test_broker_breaker_flattens_on_loss_tick():
    """A realized loss past the drawdown limit flattens remaining positions
    on the same tick — no signal required (Devin Review BUG_0004)."""
    broker = PaperBroker()
    eq = {"v": 1000.0}
    broker.equity_ref = lambda: eq["v"]
    broker.max_drawdown_limit = 0.04
    orig = broker._record
    broker._record = lambda f: (orig(f), eq.update(v=eq["v"] + f.pnl))[0]

    async def go():
        # two positions
        from runtime.tradegate.broker import Order
        for sym in ("AAA", "BBB"):
            o = Order(symbol=sym, side=Side.BUY,
                      strategy=Strategy.ALPHA_MOMENTUM, capital=1000,
                      stop_price=90, take_profit=110,
                      placed_ts=1.0, expires_ts=999.0)
            await broker.submit(o, 100.0)
        # AAA stops out with a 60% loss → dd > 4% → BBB flattened too
        t = Tick(symbol="AAA", timestamp=time.time(), price=40.0,
                 bid=39.9, ask=40.1, bids_depth=1e5, asks_depth=1e5,
                 volume_delta=1, high=40.5, low=39.0)
        return await broker.on_tick(t)

    fills = asyncio.run(go())
    kinds = {f.symbol: f.kind for f in fills}
    assert kinds.get("AAA") == "EXIT_STOP"
    assert kinds.get("BBB") == "EXIT_KILL"
    assert not broker.positions


def test_exec_latency_degrade():
    cfg = EngineConfig(latency_degrade_ms=1.0)  # everything is "slow"
    store = ConfigStore()
    store.swap(**cfg.to_dict())
    q_in, q_out = asyncio.Queue(), asyncio.Queue()
    ex = ExecutionAgent(q_in, q_out, PaperBroker(), store)
    e = _evt()
    e.sized_capital = 10.0
    e.stop_price, e.take_profit = 99.0, 101.0
    e.ingest_ts = time.time() - 60  # 60s-stale event — beyond degrade limit

    async def go():
        await q_in.put(e)
        await q_in.put(None)
        await asyncio.gather(asyncio.create_task(ex.run()), return_exceptions=True)

    asyncio.run(go())
    assert ex.degraded_skips == 1
    assert asyncio.run(q_out.get()) is None  # only the sentinel — entry refused


def test_broker_cancel_all():
    b = PaperBroker()
    from runtime.tradegate.broker import Order
    o = Order(symbol="SPY", side=Side.BUY, strategy=Strategy.ALPHA_MOMENTUM,
              capital=100, stop_price=90, take_profit=110,
              placed_ts=1.0, expires_ts=2.0)
    b.resting["x"] = o
    assert b.cancel_all() == 1 and not b.resting


def test_proc_mesh_smoke():
    """The process-per-agent mesh runs end-to-end over synthetic ticks."""
    from runtime.tradegate.proc_orchestrator import run_procs
    stats = asyncio.run(run_procs(steps=200))
    assert stats["ticks"] == 200
    assert stats["procs"] == 8
    assert stats["stuck"] == []
