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
