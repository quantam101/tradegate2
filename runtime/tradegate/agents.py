"""The nine micro-agents. Each is a single-purpose coroutine reading one
inbound queue and writing to the next — no shared mutable state; the only
shared object is the immutable config snapshot from ``ConfigStore``.

Agents 4 and 5 run in parallel and merge at Agent 6's queue, matching the
spec's architecture matrix.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import deque

from .broker import Order, PaperBroker
from .config import ConfigStore
from .events import MarketEvent, Side, Signal, Strategy

log = logging.getLogger("tradegate")

# ---------------------------------------------------------------- Agent 1


class IngestAgent:
    """Normalizes raw Ticks into MarketEvents; the only stamp of wall time."""

    def __init__(self, out: asyncio.Queue[MarketEvent]):
        self.out = out
        self.count = 0

    async def run(self, feed_iter) -> None:
        async for tick in feed_iter:
            self.count += 1
            await self.out.put(MarketEvent(tick=tick, event_id=f"EVT-{self.count}"))
        await self.out.put(None)  # sentinel: feed exhausted


# ---------------------------------------------------------------- Agent 2


class DepthCvdAgent:
    """Computes order-book imbalance and running Cumulative Volume Delta."""

    def __init__(self, q_in, q_out, store: ConfigStore, window: int = 50):
        self.q_in, self.q_out, self.store = q_in, q_out, store
        self.cvd = 0.0
        self.deltas = deque(maxlen=window)

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                t = evt.tick
                evt.cvd = self.cvd = self.cvd + t.volume_delta
                evt.imbalance = t.bids_depth / t.asks_depth if t.asks_depth > 0 else 1.0
                evt.config_version = self.store.snapshot().version
                await self.q_out.put(evt)
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 2.5


class SentimentAgent:
    """Stamps macro/social sentiment onto each event (spec: SMA).

    Reads the score file written by ``runtime.tradegate.sentiment`` (lexicon
    or free-LLM refresh — offline jobs feed it, the mesh just consumes).
    Score in [-1,1]; a strongly bearish stamp (< ``bearish_veto``) vetoes
    BUY signals downstream in RiskAgent. Also casts one consensus vote
    whose confidence is the score's magnitude.
    """

    def __init__(self, q_in, q_out, path=None, bearish_veto: float = -0.5):
        self.q_in, self.q_out = q_in, q_out
        from .sentiment import SENTIMENT_PATH
        self.path = path or SENTIMENT_PATH
        self._cache_ts = 0.0
        self._cache = 0.0

    def _score(self) -> float:
        from .sentiment import load
        now = time.time()
        if now - self._cache_ts > 60:  # re-read at most once a minute
            self._cache = load(self.path)
            self._cache_ts = now
        return self._cache

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                s = evt.sentiment = self._score()
                evt.votes.append({"agent": "sentiment",
                                  "side": Side.BUY.value if s > 0.1 else
                                          (Side.SELL.value if s < -0.1 else Side.HOLD.value),
                                  "confidence": round(abs(s), 3)})
                await self.q_out.put(evt)
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 3


class RegimeAgent:
    """Classifies market state and computes rolling ATR.

    Real implementation of the spec's classifier: ATR-based trend/vol
    context + imbalance/CVD gating, not a single threshold.
    """

    def __init__(self, q_in, q_alpha, q_beta, q_drop, store: ConfigStore):
        self.q_in, self.q_alpha, self.q_beta, self.q_drop = q_in, q_alpha, q_beta, q_drop
        self.store = store
        self.tr_window = deque(maxlen=64)
        self.returns = deque(maxlen=64)

    def _atr(self, cfg) -> float:
        if len(self.tr_window) < 2:
            return 0.0
        trs = list(self.tr_window)[-cfg.atr_window:]
        return sum(trs) / len(trs)

    async def run(self) -> None:
        last_price: float | None = None
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    for q in (self.q_alpha, self.q_beta, self.q_drop):
                        await q.put(None)
                    return
                cfg = self.store.snapshot()
                t = evt.tick
                if last_price:
                    tr = max(t.high - t.low, abs(t.high - last_price), abs(t.low - last_price))
                    self.tr_window.append(tr)
                    self.returns.append((t.price - last_price) / last_price)
                last_price = t.price
                evt.atr = self._atr(cfg)

                vol = statistics.pstdev(self.returns) if len(self.returns) > 10 else 0.0
                trend = abs(sum(self.returns)) if len(self.returns) > 10 else 0.0

                if evt.imbalance >= cfg.min_imbalance and evt.cvd > cfg.cvd_min:
                    evt.regime = "LIQUIDITY_SWEEP_BREAKOUT"
                    evt.votes.append({"agent": "regime", "side": Side.BUY.value,
                                      "confidence": min(1.0, evt.imbalance / (cfg.min_imbalance * 1.5))})
                    await self.q_alpha.put(evt)
                elif 0.7 <= evt.imbalance < cfg.min_imbalance and vol > 0 and trend < vol * 8:
                    evt.regime = "MEAN_REVERSION_RANGE"
                    evt.votes.append({"agent": "regime", "side": Side.BUY.value,
                                      "confidence": 0.6})
                    await self.q_beta.put(evt)
                else:
                    evt.regime = "NOISE_LOW_EDGE"
                    await self.q_drop.put(evt)
            finally:
                self.q_in.task_done()


# ------------------------------------------------------- Agents 4 & 5


class AlphaStrategyAgent:
    """Momentum entries on confirmed depth sweeps with positive CVD."""

    def __init__(self, q_in, q_out):
        self.q_in, self.q_out = q_in, q_out

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                evt.signal = Signal(Side.BUY, Strategy.ALPHA_MOMENTUM,
                                    f"imbalance={evt.imbalance:.2f} cvd={evt.cvd:.1f}")
                evt.votes.append({"agent": "alpha", "side": Side.BUY.value,
                                  "confidence": min(1.0, evt.imbalance / 3.0)})
                await self.q_out.put(evt)
            finally:
                self.q_in.task_done()


class BetaStrategyAgent:
    """Mean-reversion entries on range dips: buy after a down tick in a range."""

    def __init__(self, q_in, q_out):
        self.q_in, self.q_out = q_in, q_out
        self.prev_price: float | None = None

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                dip = self.prev_price is not None and evt.tick.price < self.prev_price
                self.prev_price = evt.tick.price
                evt.signal = Signal(
                    Side.BUY if dip else Side.HOLD, Strategy.BETA_REVERSION,
                    "range dip" if dip else "range, no dip")
                evt.votes.append({"agent": "beta",
                                  "side": Side.BUY.value if dip else Side.HOLD.value,
                                  "confidence": 0.7 if dip else 0.0})
                await self.q_out.put(evt)
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 6


class RiskAgent:
    """Fractional Kelly sizing + drawdown circuit breaker.

    Position size = equity * kelly_fraction * safety_factor, capped at
    equity * max_trade_fraction. Halts all flow if realized equity
    drawdown exceeds ``max_drawdown_limit`` — that is the breaker trip,
    not merely a per-trade cap (a spec bug fixed here).
    """

    def __init__(self, q_in, q_out, store: ConfigStore, equity_ref,
                 on_halt=None):
        self.q_in, self.q_out, self.store = q_in, q_out, store
        self.equity_ref = equity_ref          # callable -> current equity
        self.on_halt = on_halt                # async callable: flatten + cancel
        self.peak_equity: float | None = None
        self.halted = False
        self.vetoes = {"fat_finger": 0, "slippage": 0, "sentiment": 0,
                       "consensus": 0}

    def _quorum(self, evt: MarketEvent, cfg) -> bool:
        """Consensus rule: orders above the notional threshold need
        >= consensus_min_votes votes each at >= consensus_min_score
        confidence (spec: 3/4 quorum at >0.82)."""
        good = [v for v in evt.votes
                if v.get("confidence", 0.0) >= cfg.consensus_min_score]
        return len(good) >= cfg.consensus_min_votes

    @staticmethod
    def kelly_fraction(win_rate: float, payoff: float) -> float:
        f = (win_rate * payoff - (1 - win_rate)) / payoff
        return max(0.0, f)

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                if evt.signal.side == Side.HOLD:
                    continue
                cfg = self.store.snapshot()
                equity = self.equity_ref()
                self.peak_equity = max(self.peak_equity or equity, equity)
                dd = 1 - equity / self.peak_equity
                if self.halted or dd >= cfg.max_drawdown_limit:
                    if not self.halted and self.on_halt:
                        # Kill-switch: cancel resting orders + flatten to cash
                        try:
                            await self.on_halt(evt.tick.price, evt.tick.timestamp)
                        except Exception as e:  # noqa: BLE001 — breaker must never kill the agent loop
                            log.error("[Agent 6] kill-switch flatten failed: %s", e)
                    self.halted = True
                    log.warning("[Agent 6] drawdown breaker tripped (%.2f%% >= %.2f%%) — halting",
                                dd * 100, cfg.max_drawdown_limit * 100)
                    continue

                # SMA veto: strongly bearish macro sentiment blocks longs
                if evt.signal.side == Side.BUY and evt.sentiment <= -0.5:
                    self.vetoes["sentiment"] += 1
                    continue

                # Slippage guardrail: refuse if ref price deviates > cap
                # from the bid/ask mid (spec: 0.40% vs NBBO).
                mid = (evt.tick.bid + evt.tick.ask) / 2
                if mid > 0 and abs(evt.tick.price - mid) / mid > cfg.max_slippage_bps / 1e4:
                    self.vetoes["slippage"] += 1
                    continue

                kf = self.kelly_fraction(cfg.rolling_win_rate, cfg.rolling_payout_ratio)
                alloc = equity * kf * cfg.safety_factor
                evt.sized_capital = min(alloc, equity * cfg.max_trade_fraction,
                                        cfg.max_notional_usd)
                if evt.sized_capital > cfg.consensus_threshold_usd and not self._quorum(evt, cfg):
                    self.vetoes["consensus"] += 1
                    continue
                if evt.sized_capital <= 0:
                    continue
                stop_dist = evt.atr * cfg.atr_multiplier or evt.tick.price * 0.01
                evt.stop_price = evt.tick.price - stop_dist
                evt.take_profit = evt.tick.price + stop_dist * 1.5
                await self.q_out.put(evt)
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 7


class ExecutionAgent:
    """Submits sized orders to the broker and applies order-expiry rules."""

    def __init__(self, q_in, q_out, broker: PaperBroker, store: ConfigStore):
        self.q_in, self.q_out, self.broker, self.store = q_in, q_out, broker, store
        self.cancellations = 0
        self.degraded_skips = 0

    async def run(self) -> None:
        while True:
            evt: MarketEvent | None = await self.q_in.get()
            try:
                if evt is None:
                    await self.q_out.put(None)
                    return
                cfg = self.store.snapshot()
                # Latency anomaly: beyond the degrade threshold the spec drops
                # to passive market-making — our venue is market orders, so
                # "passive" here means *refuse the entry* rather than chase.
                if evt.latency_ms() > cfg.latency_degrade_ms:
                    evt.degraded = True
                    self.degraded_skips += 1
                    log.warning("[Agent 7] latency %.0fms > degrade limit — skipping entry",
                                evt.latency_ms())
                    continue
                now = evt.tick.timestamp if evt.tick.timestamp > 1e6 else time.time()
                order = Order(
                    symbol=evt.tick.symbol, side=evt.signal.side,
                    strategy=evt.signal.strategy, capital=evt.sized_capital,
                    stop_price=evt.stop_price, take_profit=evt.take_profit,
                    placed_ts=now, expires_ts=now + cfg.cancel_after_sec,
                )
                fill = await self.broker.submit(order, evt.tick.price)
                if fill:
                    await self.q_out.put((evt, fill))
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 8


class TelemetryAgent:
    """Async alert/telemetry fan-out. Webhooks are optional and dispatched
    off the hot path via ``asyncio.to_thread`` so the pipeline never waits
    on network I/O."""

    def __init__(self, q_in, audit_log=None, discord_url: str | None = None,
                 telegram_token: str | None = None, telegram_chat: str | None = None):
        self.q_in = q_in
        self.audit_log = audit_log  # callable(dict) -> None, e.g. audit_log.append
        self.discord_url = discord_url
        self.telegram_token = telegram_token
        self.telegram_chat = telegram_chat

    async def emit(self, kind: str, payload: dict) -> None:
        rec = {"kind": kind, "ts": time.time(), **payload}
        if self.audit_log:
            self.audit_log(rec)
        if self.discord_url or self.telegram_token:
            asyncio.create_task(self._dispatch(rec))

    async def _dispatch(self, rec: dict) -> None:
        import urllib.request
        text = rec.get("text") or f"{rec['kind']}: {rec}"
        try:
            if self.discord_url:
                body = str.encode(__import__("json").dumps(
                    {"username": "TradeGate", "content": text[:1900]}))
                await asyncio.to_thread(
                    urllib.request.urlopen,
                    urllib.request.Request(self.discord_url, data=body,
                                           headers={"Content-Type": "application/json"}))
            if self.telegram_token and self.telegram_chat:
                import json as _j
                body = _j.dumps({"chat_id": self.telegram_chat, "text": text}).encode()
                url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                await asyncio.to_thread(
                    urllib.request.urlopen,
                    urllib.request.Request(url, data=body,
                                           headers={"Content-Type": "application/json"}))
        except Exception as e:  # never let alerts kill the pipeline
            log.error("[Agent 8] dispatch failed: %s", e)

    async def run(self) -> None:
        while True:
            item = await self.q_in.get()
            try:
                if item is None:
                    return
                evt, fill = item
                await self.emit("TRADE_FILL", {
                    "text": (f"{fill.side.value} {fill.symbol} qty={fill.qty:.4f} "
                             f"@ {fill.price:.2f} ({evt.signal.strategy.value})"),
                    "symbol": fill.symbol, "strategy": evt.signal.strategy.value,
                    "regime": evt.regime, "capital": evt.sized_capital,
                    "price": fill.price, "config_version": evt.config_version,
                })
            finally:
                self.q_in.task_done()


# ---------------------------------------------------------------- Agent 9


class OptimizerAgent:
    """Periodic walk-forward parameter optimization.

    Runs the real backtester (``backtest.run_backtest``) over recent
    tick windows on a thread, then hot-swaps the config atomically via
    ``ConfigStore.swap`` — never mutating a live manifest.
    """

    def __init__(self, store: ConfigStore, telemetry: TelemetryAgent | None,
                 objective, interval_sec: float = 3600.0, n_trials: int = 24):
        self.store = store
        self.telemetry = telemetry
        self.objective = objective      # callable(dict) -> (score, report)
        self.interval = interval_sec
        self.n_trials = n_trials
        self.shutdown = asyncio.Event()
        self.best_score = float("-inf")

    async def run(self) -> None:
        while not self.shutdown.is_set():
            try:
                score, params, report = await asyncio.to_thread(self._optimize)
                if score > self.best_score:
                    self.best_score = score
                    new = self.store.swap(**params)
                    log.info("[Agent 9] hot-swap v%d score=%.3f params=%s",
                             new.version, score, params)
                    if self.telemetry:
                        await self.telemetry.emit("OPTIMIZATION_SWAP",
                                                  {"params": params, "score": score,
                                                   "report": report})
            except Exception as e:
                log.error("[Agent 9] pass failed: %s", e)
            try:
                await asyncio.wait_for(self.shutdown.wait(), self.interval)
            except asyncio.TimeoutError:
                pass

    def _optimize(self):
        from .optimizer import tpe_search
        return tpe_search(self.objective, n_trials=self.n_trials)
