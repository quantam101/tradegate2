"""Canonical event types flowing through the mesh."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Strategy(str, Enum):
    ALPHA_MOMENTUM = "ALPHA_MOMENTUM"   # depth sweep / breakout
    BETA_REVERSION = "BETA_REVERSION"   # mean reversion in range
    NONE = "NONE"


@dataclass(frozen=True)
class Tick:
    """Normalized market frame produced by a MarketDataSource.

    ``bids_depth``/``asks_depth`` are aggregate top-of-book depth sums
    (or normalized equivalents) — real exchange adapters compute these
    from L2 book snapshots; the replay/synthetic feeds carry them.
    """

    symbol: str
    timestamp: float
    price: float
    bid: float
    ask: float
    bids_depth: float
    asks_depth: float
    volume_delta: float  # signed taker volume this frame (CVD increment)
    high: float = 0.0    # bar high (for ATR); defaults to price
    low: float = 0.0     # bar low; defaults to price

    def __post_init__(self):
        if not self.high:
            object.__setattr__(self, "high", self.price)
        if not self.low:
            object.__setattr__(self, "low", self.price)


@dataclass
class Signal:
    side: Side
    strategy: Strategy
    reason: str = ""


@dataclass
class MarketEvent:
    """Mutable pipeline envelope carried between agents via queues.

    Each agent stamps its own fields; nothing else is shared. The config
    an agent used is captured per-event in ``config_version`` for audit.
    """

    tick: Tick
    event_id: str = ""
    cvd: float = 0.0
    imbalance: float = 1.0
    atr: float = 0.0
    regime: str = "UNKNOWN"
    signal: Signal = field(default_factory=lambda: Signal(Side.HOLD, Strategy.NONE))
    sized_capital: float = 0.0
    stop_price: float = 0.0
    take_profit: float = 0.0
    config_version: int = 0
    ingest_ts: float = field(default_factory=time.time)
    # ── Governance stamps ──────────────────────────────────────────────
    votes: list = field(default_factory=list)  # {agent, side, confidence}
    sentiment: float = 0.0                     # [-1,1] from SentimentAgent
    degraded: bool = False                     # latency-anomaly passive mode
    halt: bool = False                         # drawdown kill-switch: flatten all

    def latency_ms(self) -> float:
        return (time.time() - self.ingest_ts) * 1000.0
