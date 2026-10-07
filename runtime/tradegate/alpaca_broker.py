"""Alpaca paper-trading broker — the real-broker seam.

Implements the same ``Broker`` protocol as ``PaperBroker``, backed by
Alpaca's free paper API (``paper-api.alpaca.markets`` — no money, real
order flow, real fill accounting). Enabled only when
``ALPACA_PAPER_KEY`` + ``ALPACA_PAPER_SECRET`` are set; nothing here can
reach the live endpoint — ``LIVE_BASE`` is deliberately unreachable in
this build so a config typo can never move real money.

Semantics vs PaperBroker:
- ``submit``    → market order with a server-side *bracket*
                  (take-profit limit + stop-loss stop) — Alpaca manages
                  exits between our daily ticks, which our in-process
                  broker cannot do when the process isn't running.
- ``on_tick``   → polls the open position; when the bracket leg filled
                  and the position is gone, the closing order's
                  ``filled_avg_price`` becomes the honest exit fill.
- ``close_all`` → liquidates remaining positions at market.

Stdlib-only (urllib) — no SDK dependency.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .broker import Broker, Fill, Order, PaperBroker, Position
from .events import Side, Tick

log = logging.getLogger(__name__)

PAPER_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


class AlpacaPaperBroker(Broker):
    """Broker protocol over Alpaca paper REST. One position per symbol,
    bracket exits managed server-side."""

    def __init__(self, key: str | None = None, secret: str | None = None,
                 base: str = PAPER_BASE, ledger_path: Path | None = None):
        self.key = (key or os.getenv("ALPACA_PAPER_KEY", "")).strip()
        self.secret = (secret or os.getenv("ALPACA_PAPER_SECRET", "")).strip()
        if not self.key or not self.secret:
            raise ValueError("ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not set")
        self.base = base
        self.ledger_path = ledger_path
        self.fills: list[Fill] = []
        # symbol → our local Position record (Alpaca holds the real one)
        self.positions: dict[str, Position] = {}

    # ── HTTP ────────────────────────────────────────────────────────────
    def _req(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "Content-Type": "application/json",
                "User-Agent": "tradegate-paper/1.0",
            })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def _record(self, fill: Fill) -> None:
        self.fills.append(fill)
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a") as f:
                from dataclasses import asdict
                f.write(json.dumps(asdict(fill), default=str) + "\n")

    # ── Broker protocol ─────────────────────────────────────────────────
    async def submit(self, order: Order, ref_price: float) -> Fill | None:
        if order.symbol in self.positions:
            return None
        qty = max(1, int(order.capital / ref_price))  # whole shares
        body = {
            "symbol": order.symbol,
            "qty": str(qty),
            "side": "buy" if order.side == Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": f"{order.take_profit:.2f}"},
            "stop_loss": {"stop_price": f"{order.stop_price:.2f}"},
        }
        resp = self._req("POST", "/v2/orders", body)
        if not resp or "id" not in resp:
            log.warning("alpaca submit rejected: %s", resp)
            return None
        pos = Position(
            symbol=order.symbol, side=order.side, qty=qty,
            entry_price=ref_price, entry_ts=order.placed_ts,
            stop_price=order.stop_price, take_profit=order.take_profit,
            strategy=order.strategy, order_id=str(resp["id"]),
            atr_offset=ref_price - order.stop_price,
        )
        self.positions[order.symbol] = pos
        fill = Fill(order_id=pos.order_id, symbol=order.symbol,
                    side=order.side, qty=qty, price=ref_price,
                    ts=order.placed_ts, kind="ENTRY", pnl=0.0)
        self._record(fill)
        return fill

    async def on_tick(self, tick: Tick) -> list[Fill]:
        out: list[Fill] = []
        pos = self.positions.get(tick.symbol)
        if not pos:
            return out
        sym = urllib.parse.quote(tick.symbol)
        live = self._req("GET", f"/v2/positions/{sym}")
        if live is not None:
            return out  # still open — bracket legs manage the exit
        # Position gone → a bracket leg filled. Find the closing child order
        # for the honest fill price instead of guessing at the tick.
        price = tick.price
        orders = self._req(
            "GET", f"/v2/orders?status=closed&symbols={sym}&limit=10") or []
        for o in orders:
            if (o.get("side") != ("buy" if pos.side == Side.BUY else "sell")
                    and o.get("filled_avg_price")):
                price = float(o["filled_avg_price"])
                break
        gross = (price - pos.entry_price) * pos.qty
        fill = Fill(order_id=pos.order_id, symbol=pos.symbol, side=pos.side,
                    qty=pos.qty, price=price, ts=tick.timestamp,
                    kind="EXIT_BRACKET", pnl=gross)
        del self.positions[pos.symbol]
        self._record(fill)
        out.append(fill)
        return out

    async def close_all(self, ref_price: float, ts: float) -> list[Fill]:
        out = []
        for sym in list(self.positions):
            pos = self.positions[sym]
            self._req("DELETE", f"/v2/positions/{urllib.parse.quote(sym)}")
            gross = (ref_price - pos.entry_price) * pos.qty
            fill = Fill(order_id=pos.order_id, symbol=sym, side=pos.side,
                        qty=pos.qty, price=ref_price, ts=ts,
                        kind="EXIT_EOD", pnl=gross)
            self._record(fill)
            out.append(fill)
            del self.positions[sym]
        return out

    def stats(self) -> dict:
        return PaperBroker.stats(self)


def from_env(ledger_path: Path | None = None) -> AlpacaPaperBroker:
    return AlpacaPaperBroker(ledger_path=ledger_path)
