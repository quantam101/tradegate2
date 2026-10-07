"""Mesh orchestrator: wires all nine agents to queues and runs them.

Modes:
  paper    — SyntheticFeed (or --replay FILE) through the live pipeline,
             PaperBroker fills, telemetry to audit JSONL (+optional webhooks).
  backtest — same pipeline, no pacing; prints the real metrics table.
  optimize — walk-forward TPE search; writes the best manifest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .agents import (
    AlphaStrategyAgent,
    BetaStrategyAgent,
    DepthCvdAgent,
    ExecutionAgent,
    IngestAgent,
    OptimizerAgent,
    RegimeAgent,
    RiskAgent,
    SentimentAgent,
    TelemetryAgent,
)
from .broker import Broker, PaperBroker
from .config import ConfigStore
from .feed import MarketDataSource

log = logging.getLogger("tradegate")


class TradeGateOrchestrator:
    def __init__(self, store: ConfigStore | None = None,
                 initial_capital: float = 1000.0,
                 ledger_path: Path | None = None,
                 audit_path: Path | None = None,
                 discord_url: str | None = None,
                 telegram_token: str | None = None,
                 telegram_chat: str | None = None,
                 optimizer_interval: float = 3600.0,
                 optimizer_objective=None,
                 broker: Broker | None = None):
        self.store = store or ConfigStore()
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.broker = broker or PaperBroker(ledger_path=ledger_path)
        # Realized-equity breaker: flatten fires the tick a loss breaches
        # the limit, even with no new signal in flight.
        self.broker.equity_ref = lambda: self.equity
        self.broker.drawdown_limit_ref = (
            lambda: self.store.snapshot().max_drawdown_limit)
        self.audit_path = Path(audit_path) if audit_path else None

        q_depth, q_regime_out = asyncio.Queue(), asyncio.Queue()
        q_senti = asyncio.Queue()
        q_alpha, q_beta, q_drop = asyncio.Queue(), asyncio.Queue(), asyncio.Queue()
        q_risk, q_exec, q_telem = asyncio.Queue(), asyncio.Queue(), asyncio.Queue()

        # merge alpha/beta into one risk queue via fan-in
        q_signals = asyncio.Queue()
        self.q_depth = q_depth
        self.q_signals = q_signals
        self.q_telem = q_telem
        self._aux_queues = (q_regime_out, q_alpha, q_beta, q_drop, q_risk, q_exec)
        # every queue an event traverses, in order — used to flush the mesh
        # per tick on un-paced feeds (replay/synthetic) so exits stay honest
        self.stages = (q_depth, q_senti, q_regime_out, q_alpha, q_beta,
                       q_signals, q_risk, q_exec, q_telem)

        def audit(rec):
            if self.audit_path:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                with self.audit_path.open("a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")

        orig_record = self.broker._record
        def record(fill):
            orig_record(fill)
            self.equity += fill.pnl
        self.broker._record = record  # type: ignore[attr-defined]

        self.ingest = IngestAgent(q_depth)
        self.depth = DepthCvdAgent(q_depth, q_senti, self.store)
        self.sentiment = SentimentAgent(q_senti, q_regime_out)
        self.regime = RegimeAgent(q_regime_out, q_alpha, q_beta, q_drop, self.store)
        self.alpha = AlphaStrategyAgent(q_alpha, q_signals, self.store)
        self.beta = BetaStrategyAgent(q_beta, q_signals, self.store)
        self.risk = RiskAgent(q_signals, q_risk, self.store, lambda: self.equity)
        self.execution = ExecutionAgent(q_risk, q_telem, self.broker, self.store)
        self.telemetry = TelemetryAgent(
            q_telem, audit_log=audit, discord_url=discord_url,
            telegram_token=telegram_token, telegram_chat=telegram_chat)
        self.optimizer = (OptimizerAgent(self.store, self.telemetry,
                                         optimizer_objective, optimizer_interval)
                          if optimizer_objective else None)

    async def run(self, feed: MarketDataSource, symbol: str | None = None,
                  run_optimizer: bool = False) -> None:
        # Alpha and beta each forward a sentinel into q_signals at end of
        # stream; RiskAgent returns on the first and the second is dropped.
        tasks = [
            asyncio.create_task(self.depth.run()),
            asyncio.create_task(self.sentiment.run()),
            asyncio.create_task(self.regime.run()),
            asyncio.create_task(self.alpha.run()),
            asyncio.create_task(self.beta.run()),
            asyncio.create_task(self.risk.run()),
            asyncio.create_task(self.execution.run()),
            asyncio.create_task(self.telemetry.run()),
            asyncio.create_task(self._dropped()),
        ]
        if self.optimizer and run_optimizer:
            tasks.append(asyncio.create_task(self.optimizer.run()))
        await self.ingest.run(feed.stream(symbol))
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.optimizer:
            self.optimizer.shutdown.set()

    async def _dropped(self) -> None:
        q_drop = self._aux_queues[3]
        while await q_drop.get() is not None:
            pass


async def run_paper(symbol: str = "PAPER/USD", steps: int = 5000, **kw):
    from .feed import SyntheticFeed
    orch = TradeGateOrchestrator(**kw)
    # broker.on_tick needs raw ticks — wire via feed wrapper
    feed = _TapFeed(SyntheticFeed(symbol=symbol, steps=steps),
                    orch.broker, orch.stages)
    t0 = time.time()
    await orch.run(feed, symbol)
    stats = orch.broker.stats()
    log.info("paper run done in %.1fs — %s", time.time() - t0, stats)
    return orch, stats


class _TapFeed:
    """Wraps a feed so every tick hits broker.on_tick first, then is
    awaited through the whole mesh before the next tick arrives — same
    ordering guarantee the backtester uses."""

    def __init__(self, inner: MarketDataSource, broker: PaperBroker,
                 stages=()):
        self.inner, self.broker, self.stages = inner, broker, stages

    async def stream(self, symbol: str | None = None):
        async for tick in self.inner.stream(symbol):
            await self.broker.on_tick(tick)
            yield tick
            for q in self.stages:
                await q.join()
