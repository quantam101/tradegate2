"""Replay backtester: drives the real agent pipeline over a recorded or
synthetic tick window and reports honest metrics from the broker ledger —
this is what Agent 9 optimizes, replacing the spec's synthetic objective
curve.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections.abc import Iterable

from .agents import (
    AlphaStrategyAgent,
    BetaStrategyAgent,
    DepthCvdAgent,
    ExecutionAgent,
    RegimeAgent,
    RiskAgent,
)
from .broker import PaperBroker
from .config import ConfigStore, EngineConfig
from .events import MarketEvent, Tick


def _equity_curve(initial: float, exits) -> list[float]:
    eq, curve = initial, []
    for f in sorted(exits, key=lambda f: f.ts):
        eq += f.pnl
        curve.append(eq)
    return curve


def compute_metrics(initial_capital: float, fills) -> dict:
    exits = [f for f in fills if f.kind.startswith("EXIT")]
    if not exits:
        return {"trades": 0, "net_pnl": 0.0, "roi": 0.0, "win_rate": 0.0,
                "max_drawdown": 0.0, "profit_factor": 0.0, "sharpe": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0}
    pnls = [f.pnl for f in exits]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    curve = _equity_curve(initial_capital, exits)
    peak, max_dd = initial_capital, 0.0
    for eq in curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, 1 - eq / peak)
    sharpe = (statistics.mean(pnls) / statistics.pstdev(pnls) * math.sqrt(len(pnls))
              if len(pnls) > 1 and statistics.pstdev(pnls) > 0 else 0.0)
    return {
        "trades": len(exits),
        "net_pnl": sum(pnls),
        "roi": sum(pnls) / initial_capital,
        "win_rate": len(wins) / len(exits),
        "max_drawdown": max_dd,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else float("inf"),
        "sharpe": sharpe,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": abs(sum(losses) / len(losses)) if losses else 0.0,
    }


async def _run_pipeline(ticks: Iterable[Tick], config: EngineConfig,
                        initial_capital: float) -> PaperBroker:
    """Wire Agents 2–7 over queues exactly as the live orchestrator does,
    minus ingestion (ticks supplied directly) and telemetry (no-op)."""
    store = ConfigStore(config)
    broker = PaperBroker()
    equity = {"v": initial_capital}
    broker.equity_ref = lambda: equity["v"]
    broker.max_drawdown_limit = config.max_drawdown_limit

    q_depth, q_alpha, q_beta, q_sig, q_risk, q_exec = (
        asyncio.Queue(), asyncio.Queue(), asyncio.Queue(),
        asyncio.Queue(), asyncio.Queue(), asyncio.Queue())

    depth = DepthCvdAgent(q_depth, q_sig, store)
    regime = RegimeAgent(q_sig, q_alpha, q_beta, asyncio.Queue(), store)
    alpha = AlphaStrategyAgent(q_alpha, q_risk, store)
    beta = BetaStrategyAgent(q_beta, q_risk, store)
    risk = RiskAgent(q_risk, q_exec, store, lambda: equity["v"])
    execution = ExecutionAgent(q_exec, asyncio.Queue(), broker, store)

    # track equity from fills in real time so RiskAgent sees true drawdown
    orig_record = broker._record
    def record(fill):
        orig_record(fill)
        equity["v"] += fill.pnl
    broker._record = record  # type: ignore[attr-defined]

    tasks = [asyncio.create_task(a.run()) for a in
             (depth, regime, alpha, beta, risk, execution)]

    # q_sig.join() covers the drop path too: RegimeAgent task_done's its
    # input only after the event lands on q_drop.
    stages = (q_depth, q_sig, q_alpha, q_beta, q_risk, q_exec)
    last_tick: Tick | None = None
    for tick in ticks:
        last_tick = tick
        # exits fire before new signals see the tick
        await broker.on_tick(tick)
        await q_depth.put(MarketEvent(tick=tick, event_id=f"BT-{tick.timestamp}"))
        # wait for this tick to fully traverse the mesh before the next
        for q in stages:
            await q.join()
    await q_depth.put(None)
    # drain: alpha and beta each forward a sentinel to the risk queue;
    # RiskAgent returns on the first, the second is simply discarded.
    await asyncio.gather(*tasks, return_exceptions=True)
    if last_tick:
        await broker.close_all(last_tick.price, last_tick.timestamp,
                               ref_symbol=last_tick.symbol)
    return broker


def run_backtest(ticks: Iterable[Tick], config: EngineConfig | None = None,
                 initial_capital: float = 1000.0) -> dict:
    broker = asyncio.run(_run_pipeline(list(ticks),
                                     config or EngineConfig(),
                                     initial_capital))
    return compute_metrics(initial_capital, broker.fills)


def score(metrics: dict, config: EngineConfig, min_trades: int = 20) -> float:
    """Scalar objective for WFO: risk-adjusted return, hard-gated on the
    drawdown and win-rate floors of the spec."""
    if metrics["trades"] < min_trades:
        return -100.0 + metrics["trades"]
    if metrics["max_drawdown"] > config.max_drawdown_limit:
        return -50.0 - metrics["max_drawdown"] * 100
    if metrics["win_rate"] < config.min_win_rate:
        return -25.0 + metrics["win_rate"] * 10
    return metrics["roi"] * 10 + metrics["sharpe"] - metrics["max_drawdown"] * 20
