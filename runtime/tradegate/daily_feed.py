"""Real market data: daily OHLCV bars → normalized ``Tick`` stream.

Two free, keyless sources, tried in order:

1. Yahoo Finance chart API (``query1.finance.yahoo.com/v8/finance/chart``)
   — unofficial but stable; needs only a browser User-Agent.
2. Stooq CSV (``stooq.com/q/d/l/?s=spy.us&i=d``) — plain CSV, no auth,
   very reliable for US symbols (``AAPL`` → ``aapl.us``).

Each daily bar yields ONE ``Tick``: ``price`` = close, ``high``/``low`` =
the real bar range (drives the ATR stops), bid/ask straddle the close,
``volume_delta`` signed by close-vs-open, depths held constant — the
mesh treats these as honest placeholders since free daily data has no
L2 book. ~252 decision points per year per symbol.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

from .events import Tick

_UA = {"User-Agent": "Mozilla/5.0 (compatible; tradegate-paper/1.0)"}


@dataclass(frozen=True)
class Bar:
    ts: float          # unix seconds (bar open time, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


def _yahoo_bars(symbol: str, range_: str = "1y") -> list[Bar]:
    q = urllib.parse.quote(symbol)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
           f"?range={range_}&interval=1d&includePrePost=false")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    res = (data.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise ValueError(f"yahoo: no result for {symbol}")
    ts = res.get("timestamp") or []
    qd = res.get("indicators", {}).get("quote", [{}])[0]
    bars: list[Bar] = []
    for i, t in enumerate(ts):
        o, h, l, c = (qd.get(k) or [] for k in ("open", "high", "low", "close"))
        v = (qd.get("volume") or [None] * len(ts))[i]
        if i < len(o) and None not in (o[i], h[i], l[i], c[i]):
            bars.append(Bar(ts=float(t), open=float(o[i]), high=float(h[i]),
                            low=float(l[i]), close=float(c[i]),
                            volume=float(v or 0.0)))
    if not bars:
        raise ValueError(f"yahoo: empty bars for {symbol}")
    return bars


def _stooq_bars(symbol: str) -> list[Bar]:
    sym = symbol.lower()
    if "/" not in sym and "." not in sym:
        sym += ".us"  # US equity convention on Stooq
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode()
    bars: list[Bar] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            ts = datetime.strptime(row["Date"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp()
            bars.append(Bar(ts=ts, open=float(row["Open"]), high=float(row["High"]),
                            low=float(row["Low"]), close=float(row["Close"]),
                            volume=float(row.get("Volume") or 0.0)))
        except (KeyError, ValueError):
            continue
    if not bars:
        raise ValueError(f"stooq: empty bars for {symbol}")
    return bars


def fetch_bars(symbol: str, range_: str = "1y") -> list[Bar]:
    """Daily bars for ``symbol``, newest last. Yahoo → Stooq fallback."""
    try:
        return _yahoo_bars(symbol, range_)
    except (OSError, ValueError, KeyError):
        return _stooq_bars(symbol)


def buy_hold_return(bars: list[Bar]) -> float:
    """Benchmark: buy at first close, sell at last close."""
    if len(bars) < 2:
        return 0.0
    return bars[-1].close / bars[0].close - 1.0


def bars_to_ticks(symbol: str, bars: list[Bar]) -> list[Tick]:
    ticks: list[Tick] = []
    for b in bars:
        spread = max(b.close * 1e-4, 0.01)
        ticks.append(Tick(
            symbol=symbol,
            timestamp=b.ts,
            price=b.close,
            bid=b.close - spread / 2,
            ask=b.close + spread / 2,
            bids_depth=1e5,
            asks_depth=1e5,
            volume_delta=(b.volume if b.close >= b.open else -b.volume),
            high=b.high,
            low=b.low,
            open=b.open,
        ))
    return ticks


class DailyBarsFeed:
    """``MarketDataSource`` over real daily bars for one symbol."""

    def __init__(self, symbol: str, range_: str = "1y"):
        self.symbol = symbol
        self.range = range_

    async def stream(self, symbol: str | None = None) -> AsyncIterator[Tick]:
        if symbol and symbol != self.symbol:
            return
        for t in bars_to_ticks(self.symbol, fetch_bars(self.symbol, self.range)):
            yield t
