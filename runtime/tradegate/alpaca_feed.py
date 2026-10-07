"""Alpaca live trade feed — real market data for the mesh.

Streams real-time trades from Alpaca's free IEX WebSocket
(``wss://stream.data.alpaca.markets/v2/iex``) and converts each trade
into a :class:`Tick`. Requires ``ALPACA_PAPER_KEY`` /
``ALPACA_PAPER_SECRET`` — the same free paper account also unlocks the
data stream. Paper-trading only: this feed never touches the live
broker endpoint.

Honest semantics — what this feed can and cannot tell the mesh:

- IEX trades carry price + size, **not** top-of-book depth. ``bids_depth``
  and ``asks_depth`` are therefore pinned to 1.0, which means
  ``imbalance == 1.0`` and ``LIQUIDITY_SWEEP_BREAKOUT`` can never trigger
  here — entries come from the real momentum/RSI regime path, exactly as
  on daily bars. Nothing is synthesized to look like depth.
- Trade side is not published by IEX either; ``volume_delta`` uses the
  standard tick-rule estimator (uptick = taker buy, downtick = sell).
  It is a real estimator of order flow, clearly labeled — not fabricated
  depth.
- Outside market hours the socket simply goes quiet; the mesh idles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator

from .events import Tick
from .feed import MarketDataSource

log = logging.getLogger(__name__)

WS_URL = "wss://stream.data.alpaca.markets/v2/iex"


def trade_to_tick(msg: dict, last_price: dict[str, float]) -> Tick:
    """Convert one Alpaca trade message to a Tick.

    ``last_price`` is per-symbol state for the tick-rule volume sign
    (uptick → +size, downtick → -size, unchanged → 0 contribution).
    """
    sym = msg["S"]
    price = float(msg["p"])
    size = float(msg.get("s", 0))
    prev = last_price.get(sym)
    if prev is None or price == prev:
        delta = 0.0
    else:
        delta = size if price > prev else -size
    last_price[sym] = price
    ts = msg.get("t", "")
    try:
        from datetime import datetime
        ts_val = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        ts_val = 0.0
    return Tick(symbol=sym, timestamp=ts_val, price=price,
                bid=price, ask=price,
                bids_depth=1.0, asks_depth=1.0,  # IEX: no depth — see docstring
                volume_delta=delta, high=price, low=price)


class AlpacaTradeFeed:
    """``MarketDataSource`` over Alpaca's IEX trade websocket."""

    def __init__(self, symbols: list[str],
                 key: str | None = None, secret: str | None = None,
                 ws_url: str = WS_URL):
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.key = (key or os.getenv("ALPACA_PAPER_KEY", "")).strip()
        self.secret = (secret or os.getenv("ALPACA_PAPER_SECRET", "")).strip()
        self.ws_url = ws_url
        if not self.key or not self.secret:
            raise ValueError("ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not set")
        if not self.symbols:
            raise ValueError("no symbols to stream")

    async def stream(self, symbol: str | None = None) -> AsyncIterator[Tick]:
        # Imported here so backtests/tests never pay for the dependency.
        from websockets.asyncio.client import connect

        want = set(self.symbols)
        if symbol:
            want &= {symbol}
        last_price: dict[str, float] = {}
        while True:
            try:
                async with connect(self.ws_url, ping_interval=20) as ws:
                    await ws.send(json.dumps({
                        "action": "auth", "key": self.key,
                        "secret": self.secret}))
                    auth = json.loads(await ws.recv())
                    log.info("alpaca ws auth: %s", auth)
                    await ws.send(json.dumps({
                        "action": "subscribe",
                        "trades": sorted(want)}))
                    async for raw in ws:
                        for msg in json.loads(raw):
                            if msg.get("T") != "t" or msg.get("S") not in want:
                                continue
                            yield trade_to_tick(msg, last_price)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect on any socket failure
                log.warning("alpaca ws dropped (%s) — reconnecting in 10s", e)
                await asyncio.sleep(10)
