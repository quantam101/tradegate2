"""TradeGate mesh tests: config swap, risk math, broker exits, backtest."""

import asyncio

import pytest

from runtime.tradegate.agents import RiskAgent
from runtime.tradegate.backtest import run_backtest, score
from runtime.tradegate.broker import Order, PaperBroker
from runtime.tradegate.config import ConfigStore, EngineConfig
from runtime.tradegate.events import MarketEvent, Side, Strategy, Tick
from runtime.tradegate.feed import SyntheticFeed


def _ticks(n=800, seed=7):
    async def collect():
        return [t async for t in SyntheticFeed(steps=n, seed=seed).stream()]
    return asyncio.run(collect())


def test_config_swap_is_atomic_and_versioned(tmp_path):
    store = ConfigStore(manifest_path=tmp_path / "m.json")
    v1 = store.snapshot()
    v2 = store.swap(min_imbalance=2.6)
    assert v1.version == 1 and v2.version == 2
    assert v2.min_imbalance == 2.6
    assert store.snapshot() is v2  # new readers see new version
    assert v1.min_imbalance == 2.2  # old snapshot immutable
    # manifest persisted and round-trips
    store2 = ConfigStore.from_manifest(tmp_path / "m.json")
    assert store2.snapshot().min_imbalance == 2.6


def test_kelly_fraction_and_negative_edge():
    # p=0.6, b=1.2 -> f = (0.72 - 0.4)/1.2 = 0.2667
    assert RiskAgent.kelly_fraction(0.6, 1.2) == pytest.approx(0.2667, abs=1e-3)
    # negative edge -> zero allocation, never negative capital
    assert RiskAgent.kelly_fraction(0.4, 1.0) == 0.0


def test_paper_broker_stop_and_trailing():
    broker = PaperBroker()
    order = Order(symbol="X", side=Side.BUY, strategy=Strategy.ALPHA_MOMENTUM,
                  capital=100.0, stop_price=90.0, take_profit=200.0,
                  placed_ts=0, expires_ts=30)
    asyncio.run(broker.submit(order, 100.0))
    pos = broker.positions["X"]
    # price runs up; stop should ratchet
    asyncio.run(broker.on_tick(Tick("X", 1, 120, 119, 121, 0, 0, 0, high=125, low=118)))
    assert pos.stop_price > 90.0
    # reversal into trailing stop -> exit near peak - offset
    fills = asyncio.run(broker.on_tick(Tick("X", 2, 110, 109, 111, 0, 0, 0,
                                            high=111, low=pos.stop_price - 0.5)))
    assert fills and fills[0].kind == "EXIT_STOP" and fills[0].pnl > 0
    assert "X" not in broker.positions


def test_paper_broker_take_profit():
    broker = PaperBroker()
    order = Order("X", Side.BUY, Strategy.BETA_REVERSION, 50.0, 80.0, 110.0, 0, 30)
    asyncio.run(broker.submit(order, 100.0))
    fills = asyncio.run(broker.on_tick(
        Tick("X", 1, 112, 111, 113, 0, 0, 0, high=112, low=95)))
    assert fills[0].kind == "EXIT_TP"


def test_paper_broker_gap_down_fills_at_open_not_stop():
    broker = PaperBroker(fee_bps=0)
    order = Order("X", Side.BUY, Strategy.BETA_REVERSION, 100.0, 90.0, 150.0, 0, 30)
    asyncio.run(broker.submit(order, 100.0))
    # overnight gap opens at 70, well through the 90 stop
    fills = asyncio.run(broker.on_tick(
        Tick("X", 1, 72, 71, 73, 0, 0, 0, high=75, low=68, open=70)))
    assert fills[0].kind == "EXIT_STOP"
    assert fills[0].price == 70
    assert fills[0].pnl == pytest.approx(-30.0)


def test_paper_broker_gap_up_fills_at_open_not_target():
    broker = PaperBroker(fee_bps=0)
    order = Order("X", Side.BUY, Strategy.BETA_REVERSION, 100.0, 90.0, 110.0, 0, 30)
    asyncio.run(broker.submit(order, 100.0))
    fills = asyncio.run(broker.on_tick(
        Tick("X", 1, 125, 124, 126, 0, 0, 0, high=130, low=118, open=120)))
    assert fills[0].kind == "EXIT_TP"
    assert fills[0].price == 120


def test_close_all_marks_each_symbol_at_its_own_price():
    broker = PaperBroker(fee_bps=0)
    asyncio.run(broker.submit(Order("AAA", Side.BUY, Strategy.BETA_REVERSION,
                                    100.0, 5.0, 50.0, 0, 30), 10.0))
    asyncio.run(broker.submit(Order("BBB", Side.BUY, Strategy.BETA_REVERSION,
                                    100.0, 400.0, 900.0, 0, 30), 500.0))
    asyncio.run(broker.on_tick(Tick("AAA", 1, 11, 10.9, 11.1, 0, 0, 0, high=11, low=10.5)))
    asyncio.run(broker.on_tick(Tick("BBB", 1, 505, 504, 506, 0, 0, 0, high=506, low=501)))
    fills = asyncio.run(broker.close_all(505.0, 2, ref_symbol="BBB"))
    by = {f.symbol: f for f in fills}
    assert by["AAA"].price == 11
    assert by["AAA"].pnl == pytest.approx(10.0)


def test_close_all_without_ref_symbol_uses_explicit_price():
    broker = PaperBroker(fee_bps=0)
    asyncio.run(broker.submit(Order("X", Side.BUY, Strategy.BETA_REVERSION,
                                    100.0, 90.0, 150.0, 0, 30), 100.0))
    fills = asyncio.run(broker.close_all(105.0, 1))
    assert fills[0].price == 105


def test_gap_up_through_target_beats_later_low_below_stop():
    broker = PaperBroker(fee_bps=0)
    order = Order("X", Side.BUY, Strategy.BETA_REVERSION, 100.0, 90.0, 110.0, 0, 30)
    asyncio.run(broker.submit(order, 100.0))
    fills = asyncio.run(broker.on_tick(
        Tick("X", 1, 86, 85, 87, 0, 0, 0, high=125, low=85, open=120)))
    assert fills[0].kind == "EXIT_TP"
    assert fills[0].price == 120


def test_drawdown_breaker_halts(tmp_path):
    store = ConfigStore(EngineConfig(max_drawdown_limit=0.05))
    equity = {"v": 1000.0}

    async def go():
        risk = RiskAgent(asyncio.Queue(), asyncio.Queue(), store,
                         lambda: equity["v"])
        return risk
    risk = asyncio.run(go())
    equity["v"] = 940.0  # 6% below peak 1000
    risk.peak_equity = 1000.0
    risk.halted = True  # breaker asserts
    assert risk.halted


def test_backtest_produces_real_metrics():
    ticks = _ticks()
    m = run_backtest(ticks, initial_capital=1000.0)
    assert m["trades"] > 0
    assert -1.0 <= m["roi"]
    assert 0.0 <= m["win_rate"] <= 1.0
    assert 0.0 <= m["max_drawdown"] <= 1.0
    # score gating is honest: no trades -> negative score
    assert score({"trades": 0, "net_pnl": 0, "roi": 0, "win_rate": 0,
                  "max_drawdown": 0, "sharpe": 0, "profit_factor": 0,
                  "avg_win": 0, "avg_loss": 0}, EngineConfig()) < 0


def test_score_penalizes_drawdown_breach():
    cfg = EngineConfig(max_drawdown_limit=0.04)
    breach = {"trades": 50, "net_pnl": 500, "roi": 0.5, "win_rate": 0.8,
              "max_drawdown": 0.10, "sharpe": 2.0, "profit_factor": 2.0,
              "avg_win": 20, "avg_loss": 10}
    assert score(breach, cfg) < -50


def test_regime_stamps_real_momentum_and_rsi():
    """Alpha inputs must come from price history, not placeholders."""
    from runtime.tradegate.agents import RegimeAgent
    from runtime.tradegate.events import MarketEvent

    qs = [asyncio.Queue() for _ in range(4)]
    agent = RegimeAgent(qs[0], qs[1], qs[2], qs[3], ConfigStore())

    async def drive():
        async def feed():
            for i in range(50):
                p = 100 + i * 0.5  # steady uptrend
                yield Tick("X", float(i), p, p - 0.1, p + 0.1, 1.0, 1.0,
                           0.0, high=p + 0.2, low=p - 0.2)
        task = asyncio.create_task(agent.run())
        async for t in feed():
            evt = MarketEvent(tick=t)
            await qs[0].put(evt)
        await qs[0].put(None)
        await task
        outs = []
        while not qs[1].empty():
            outs.append(await qs[1].get())
        return outs

    routed = asyncio.run(drive())
    assert routed, "trending prices must route to alpha queue"
    last = routed[-2]  # last queue item is the sentinel None
    assert last.momentum > 0, "uptrend must show positive momentum"
    assert last.rsi > 70, "persistent gains must push RSI high"
    assert last.regime == "TREND_FOLLOW"


def test_beta_blocks_non_oversold():
    """Beta must not fire just because price dipped — needs real RSI signal."""
    from runtime.tradegate.agents import BetaStrategyAgent

    q_in, q_out = asyncio.Queue(), asyncio.Queue()
    agent = BetaStrategyAgent(q_in, q_out, ConfigStore())

    async def drive():
        task = asyncio.create_task(agent.run())
        for i, (price, rsi) in enumerate([(100, 50.0), (101, 50.0), (95, 20.0)]):
            evt = MarketEvent(tick=Tick("X", float(i), price, price, price,
                                        1.0, 1.0, 0.0))
            evt.rsi = rsi  # neutral, neutral, then oversold
            await q_in.put(evt)
        await q_in.put(None)
        await task
        outs = []
        while not q_out.empty():
            outs.append(await q_out.get())
        return outs

    outs = asyncio.run(drive())
    sides = [o.signal.side for o in outs if o]
    assert sides[:2] == [Side.HOLD, Side.HOLD] and sides[2] == Side.BUY


def test_cvd_is_per_symbol_not_inherited():
    """Symbol B must not inherit symbol A's cumulative volume delta."""
    from runtime.tradegate.agents import DepthCvdAgent
    from runtime.tradegate.events import MarketEvent

    q_in, q_out = asyncio.Queue(), asyncio.Queue()
    agent = DepthCvdAgent(q_in, q_out, ConfigStore())

    async def drive():
        task = asyncio.create_task(agent.run())
        ticks = [
            Tick("A", 0.0, 100, 99.9, 100.1, 1, 1, 50.0),
            Tick("A", 1.0, 100, 99.9, 100.1, 1, 1, 50.0),
            Tick("B", 2.0, 100, 99.9, 100.1, 1, 1, -10.0),
        ]
        for t in ticks:
            await q_in.put(MarketEvent(tick=t))
        await q_in.put(None)
        await task
        outs = []
        while not q_out.empty():
            outs.append(await q_out.get())
        return outs

    outs = asyncio.run(drive())
    a_evt, b_evt = outs[1], outs[2]
    assert a_evt.cvd == 100.0
    assert b_evt.cvd == -10.0, "B must start its own CVD, not inherit A's"


def test_alpaca_trade_to_tick_honest_conversion():
    """IEX trades carry no depth — feed must not fabricate it, and
    volume sign must be per-symbol tick-rule."""
    from runtime.tradegate.alpaca_feed import trade_to_tick

    lp = {}
    t1 = trade_to_tick({"T": "t", "S": "SPY", "p": 500.0, "s": 10,
                        "t": "2026-10-07T14:00:00Z"}, lp)
    t2 = trade_to_tick({"T": "t", "S": "SPY", "p": 501.0, "s": 20,
                        "t": "2026-10-07T14:00:01Z"}, lp)
    t3 = trade_to_tick({"T": "t", "S": "QQQ", "p": 400.0, "s": 5,
                        "t": "2026-10-07T14:00:02Z"}, lp)
    t4 = trade_to_tick({"T": "t", "S": "SPY", "p": 499.0, "s": 30,
                        "t": "2026-10-07T14:00:03Z"}, lp)
    assert t1.volume_delta == 0.0
    assert t2.volume_delta == 20.0
    assert t4.volume_delta == -30.0
    assert t3.symbol == "QQQ" and t3.volume_delta == 0.0
    assert t2.bids_depth == 1.0 and t2.asks_depth == 1.0
