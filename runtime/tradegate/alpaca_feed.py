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

Resilience (checklist: action planning + autonomous execution):

- Reconnects use exponential backoff with jitter (``Backoff``), resetting
  after any connection that survived a minute — a flaky stretch ramps to
  5 minutes between attempts instead of hammering the endpoint forever.
- Stall watchdog: while connected, silence longer than
  ``stall_timeout_sec`` triggers a market-clock check
  (``GET /v2/clock`` on the paper API). If the market is *open* and the
  socket is quiet, the connection is declared dead: we emit a
  ``FEED_STALL`` event and force a reconnect. If the market is closed,
  silence is normal and we keep waiting — no reconnect churn overnight.
- Every reconnect and stall is reported through ``on_event(kind, payload)``
  so the telemetry agent can alert (Discord/Telegram/audit) instead of
  the failure living only in a log line nobody watches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from collections.abc import AsyncIterator, Callable

from .events import Tick
from .feed import MarketDataSource
from .resilience import Backoff

log = logging.getLogger(__name__)

WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
CLOCK_URL = "https://paper-api.alpaca.markets/v2/clock"


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
    """``MarketDataSource`` over Alpaca's IEX trade websocket.

    ``on_event`` is an optional sync callback ``(kind, payload)`` invoked
    from the stream coroutine for ``FEED_CONNECTED``, ``FEED_RECONNECT``
    and ``FEED_STALL`` — wire it to ``TelemetryAgent.emit`` to make feed
    health visible to operators. ``stall_timeout_sec=None`` disables the
    watchdog.
    """

    def __init__(self, symbols: list[str],
                 key: str | None = None, secret: str | None = None,
                 ws_url: str = WS_URL,
                 stall_timeout_sec: float | None = 300.0,
                 on_event: Callable[[str, dict], None] | None = None):
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.key = (key or os.getenv("ALPACA_PAPER_KEY", "")).strip()
        self.secret = (secret or os.getenv("ALPACA_PAPER_SECRET", "")).strip()
        self.ws_url = ws_url
        self.stall_timeout_sec = stall_timeout_sec
        self.on_event = on_event
        if not self.key or not self.secret:
            raise ValueError("ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not set")
        if not self.symbols:
            raise ValueError("no symbols to stream")

    def _emit(self, kind: str, **payload) -> None:
        if self.on_event:
            try:
                self.on_event(kind, payload)
            except Exception as e:  # telemetry must never kill the feed
                log.error("feed event callback failed: %s", e)

    def market_is_open(self) -> bool | None:
        """Alpaca market clock. ``None`` when the clock is unreachable —
        callers must not treat an unknown clock as a stall."""
        req = urllib.request.Request(
            CLOCK_URL,
            headers={"APCA-API-KEY-ID": self.key,
                     "APCA-API-SECRET-KEY": self.secret})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return bool(json.loads(r.read()).get("is_open"))
        except Exception as e:  # noqa: BLE001 — clock is advisory only
            log.warning("market clock check failed: %s", e)
            return None

    async def stream(self, symbol: str | None = None) -> AsyncIterator[Tick]:
        # Imported here so backtests/tests never pay for the dependency.
        from websockets.asyncio.client import connect

        want = set(self.symbols)
        if symbol:
            want &= {symbol}
        last_price: dict[str, float] = {}
        backoff = Backoff(base=5.0, cap=300.0)
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
                    backoff.mark_connected()
                    self._emit("FEED_CONNECTED", ws_url=self.ws_url,
                               symbols=sorted(want))
                    last_msg = asyncio.get_running_loop().time()
                    while True:
                        try:
                            # Poll so the watchdog gets a chance to run even
                            # when no data ever arrives (dead socket).
                            raw = await asyncio.wait_for(
                                ws.recv(),
                                timeout=self.stall_timeout_sec or 3600.0)
                        except asyncio.TimeoutError:
                            raw = None
                        if raw is None:
                            if not self.stall_timeout_sec:
                                continue
                            silent = asyncio.get_running_loop().time() - last_msg
                            if silent < self.stall_timeout_sec:
                                continue
                            is_open = await asyncio.to_thread(
                                self.market_is_open)
                            if is_open is not True:
                                # Market closed (or clock unknown): silence
                                # is expected — keep waiting, no churn.
                                last_msg = asyncio.get_running_loop().time()
                                continue
                            self._emit("FEED_STALL",
                                       silent_sec=round(silent, 1),
                                       symbols=sorted(want))
                            log.warning("feed stalled %.0fs during market "
                                        "hours — reconnecting", silent)
                            break  # drop to reconnect
                        last_msg = asyncio.get_running_loop().time()
                        for msg in json.loads(raw):
                            if msg.get("T") != "t" or msg.get("S") not in want:
                                continue
                            yield trade_to_tick(msg, last_price)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect on any socket failure
                delay = backoff.next()
                log.warning("alpaca ws dropped (%s) — reconnect #%d in %.1fs",
                            e, backoff.attempts, delay)
                self._emit("FEED_RECONNECT", error=str(e),
                           attempt=backoff.attempts,
                           delay_sec=round(delay, 1))
                await asyncio.sleep(delay)
