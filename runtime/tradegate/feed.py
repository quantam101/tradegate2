"""Market data sources.

``MarketDataSource`` is the single seam between the mesh and the outside
world: replay feeds (recorded JSONL ticks, used for backtests and CI),
a seeded synthetic random-walk feed (used by the paper daemon and tests),
and a stub for real exchange WebSocket adapters to implement later.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol


class MarketDataSource(Protocol):
    def stream(self, symbol: str) -> AsyncIterator[Tick]: ...


# import here to keep the public Protocol above the fold
from .events import Tick  # noqa: E402


class ReplayFeed:
    """Streams ticks from a JSONL file (one Tick-shaped dict per line)."""

    def __init__(self, path: Path, pace: float = 0.0):
        self.path = Path(path)
        self.pace = pace  # seconds between ticks; 0 = as fast as possible

    async def stream(self, symbol: Optional[str] = None) -> AsyncIterator[Tick]:
        with self.path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                t = Tick(**json.loads(line))
                if symbol and t.symbol != symbol:
                    continue
                yield t
                if self.pace:
                    await asyncio.sleep(self.pace)


class SyntheticFeed:
    """Deterministic regime-switching random-walk feed.

    Alternates trending (sweep-friendly) and ranging (reversion-friendly)
    regimes with seeded randomness so tests and backtests are repeatable.
    Depth and CVD are synthesized consistently with the regime.
    """

    def __init__(self, symbol: str = "PAPER/USD", price: float = 100.0,
                 steps: int = 5000, seed: int = 7, interval: float = 0.0):
        self.symbol = symbol
        self.price = price
        self.steps = steps
        self.interval = interval
        self.rng = random.Random(seed)

    async def stream(self, symbol: Optional[str] = None) -> AsyncIterator[Tick]:
        if symbol and symbol != self.symbol:
            return
        rng, price = self.rng, self.price
        trend = 0.0
        for i in range(self.steps):
            if i % 400 == 0:
                # regime switch: trend in [-0.0015, 0.0015] per step
                trend = rng.uniform(-0.0015, 0.0015)
            vol = 0.004
            ret = trend + rng.gauss(0, vol)
            prev = price
            price = max(0.01, price * (1 + ret))
            hi = max(prev, price) * (1 + abs(rng.gauss(0, vol / 4)))
            lo = min(prev, price) * (1 - abs(rng.gauss(0, vol / 4)))
            strong = abs(ret) > vol  # directional frames get depth skew
            bids = rng.uniform(8e4, 1.6e5)
            asks = rng.uniform(8e4, 1.6e5)
            if strong and ret > 0:
                bids, asks = asks * rng.uniform(2.2, 3.4), asks
            elif strong and ret < 0:
                bids, asks = bids, bids * rng.uniform(2.2, 3.4)
            vd = (1 if ret > 0 else -1) * rng.uniform(0, 60) * (abs(ret) / vol)
            yield Tick(
                symbol=self.symbol,
                timestamp=i,
                price=price,
                bid=price * (1 - 1e-4),
                ask=price * (1 + 1e-4),
                bids_depth=bids,
                asks_depth=asks,
                volume_delta=vd,
                high=hi,
                low=lo,
            )
            if self.interval:
                await asyncio.sleep(self.interval)


class ExchangeWebSocketFeed:
    """Seam for a real exchange adapter. Not implemented by design:

    live trading requires exchange credentials, which this repo does not
    carry (zero-spend / approval-gated). Implement ``stream()`` to yield
    normalized ``Tick`` objects and everything downstream works unchanged.
    """

    async def stream(self, symbol: str) -> AsyncIterator[Tick]:  # pragma: no cover
        raise NotImplementedError(
            "No live exchange adapter is configured. Use ReplayFeed or "
            "SyntheticFeed, or implement stream() behind approval gates."
        )
        yield  # make this an async generator
