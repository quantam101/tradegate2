"""Broker interface and the paper-trading implementation.

``PaperBroker`` fills at the next tick's mid price, manages one position
per symbol, applies ATR trailing stops + take-profit exits, enforces the
30s order-expiry semantics of resting entries (a limit order that the
market never revisits is dropped), and keeps an append-only fill ledger.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .events import Side, Strategy, Tick


@dataclass
class Order:
    symbol: str
    side: Side
    strategy: Strategy
    capital: float
    stop_price: float
    take_profit: float
    placed_ts: float
    expires_ts: float
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Position:
    symbol: str
    side: Side
    qty: float
    entry_price: float
    entry_ts: float
    stop_price: float          # trailing — only ratchets toward profit
    take_profit: float
    strategy: Strategy
    order_id: str
    peak_price: float = 0.0
    atr_offset: float = 0.0

    def __post_init__(self):
        if not self.peak_price:
            self.peak_price = self.entry_price


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    ts: float
    kind: str                  # ENTRY / EXIT_STOP / EXIT_TP / EXIT_EOD
    pnl: float = 0.0


class Broker(Protocol):
    async def submit(self, order: Order, ref_price: float) -> Fill | None: ...
    async def on_tick(self, tick: Tick) -> list[Fill]: ...
    async def close_all(self, ref_price: float, ts: float) -> list[Fill]: ...


class PaperBroker:
    """Deterministic paper broker.

    Entry model: a BUY entry fills if tick.low <= ref price (market
    reachable); otherwise the order rests until ``expires_ts`` then is
    cancelled — matching the spec's 30s auto-cancel. Exit model: a long
    exits at take_profit if tick.high >= tp, at stop_price if
    tick.low <= stop (stop checked first — conservative), else marked
    at close. Trailing stop ratchets with new highs.
    """

    def __init__(self, ledger_path: Path | None = None, fee_bps: float = 1.0):
        self.positions: dict[str, Position] = {}
        self.resting: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.fee_bps = fee_bps
        self.ledger_path = Path(ledger_path) if ledger_path else None
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _record(self, fill: Fill) -> None:
        self.fills.append(fill)
        if self.ledger_path:
            with self.ledger_path.open("a") as f:
                f.write(json.dumps(asdict(fill), default=str) + "\n")

    async def submit(self, order: Order, ref_price: float) -> Fill | None:
        if order.symbol in self.positions:
            return None  # one position per symbol
        qty = order.capital / ref_price
        fee = order.capital * self.fee_bps / 1e4
        pos = Position(
            symbol=order.symbol, side=order.side, qty=qty,
            entry_price=ref_price, entry_ts=order.placed_ts,
            stop_price=order.stop_price, take_profit=order.take_profit,
            strategy=order.strategy, order_id=order.order_id,
            atr_offset=ref_price - order.stop_price,
        )
        self.positions[order.symbol] = pos
        fill = Fill(order_id=order.order_id, symbol=order.symbol,
                    side=order.side, qty=qty, price=ref_price,
                    ts=order.placed_ts, kind="ENTRY", pnl=-fee)
        self._record(fill)
        return fill

    async def on_tick(self, tick: Tick) -> list[Fill]:
        out: list[Fill] = []
        self._breaker_hit()  # seed/update the equity peak before any exits
        pos = self.positions.get(tick.symbol)
        if not pos:
            return out
        exit_fill: Fill | None = None
        if pos.side == Side.BUY:
            pos.peak_price = max(pos.peak_price, tick.high)
            # ratchet trailing stop with price advances
            if pos.atr_offset > 0:
                pos.stop_price = max(pos.stop_price, pos.peak_price - pos.atr_offset)
            if tick.low <= pos.stop_price:
                exit_fill = self._exit(pos, pos.stop_price, tick.timestamp, "EXIT_STOP")
            elif tick.high >= pos.take_profit:
                exit_fill = self._exit(pos, pos.take_profit, tick.timestamp, "EXIT_TP")
        if exit_fill:
            out.append(exit_fill)
            # Realized-equity breaker: a loss this tick can breach the
            # drawdown limit with no new signal arriving — flatten
            # remaining positions immediately rather than waiting for
            # RiskAgent to see another signal.
            if self._breaker_hit():
                for p in list(self.positions.values()):
                    out.append(self._exit(p, tick.price, tick.timestamp,
                                          "EXIT_KILL"))
        return out

    def _breaker_hit(self) -> bool:
        """Owner-wired drawdown check on realized equity."""
        if not self.equity_ref or not self.max_drawdown_limit:
            return False
        eq = self.equity_ref()
        self._breaker_peak = max(self._breaker_peak or eq, eq)
        return self._breaker_peak > 0 and \
            1 - eq / self._breaker_peak >= self.max_drawdown_limit

    # equity_ref / max_drawdown_limit / _breaker_peak are set by the owner
    # (orchestrator / backtest / proc child) — None / 0 disables the check.
    equity_ref = None
    max_drawdown_limit = 0.0
    _breaker_peak = None

    def cancel_all(self) -> int:
        """Kill-switch: drop every resting (unfilled) order. Returns count."""
        n = len(self.resting)
        self.resting.clear()
        return n

    def _exit(self, pos: Position, price: float, ts: float, kind: str) -> Fill:
        gross = (price - pos.entry_price) * pos.qty
        fee = price * pos.qty * self.fee_bps / 1e4
        fill = Fill(order_id=pos.order_id, symbol=pos.symbol, side=pos.side,
                    qty=pos.qty, price=price, ts=ts, kind=kind, pnl=gross - fee)
        del self.positions[pos.symbol]
        self._record(fill)
        return fill

    async def close_all(self, ref_price: float, ts: float) -> list[Fill]:
        out = []
        for pos in list(self.positions.values()):
            out.append(self._exit(pos, ref_price, ts, "EXIT_EOD"))
        return out

    def stats(self) -> dict:
        exits = [f for f in self.fills if f.kind.startswith("EXIT")]
        wins = [f for f in exits if f.pnl > 0]
        losses = [f for f in exits if f.pnl <= 0]
        pnl = sum(f.pnl for f in self.fills)
        return {
            "trades": len(exits),
            "win_rate": len(wins) / len(exits) if exits else 0.0,
            "avg_win": sum(f.pnl for f in wins) / len(wins) if wins else 0.0,
            "avg_loss": abs(sum(f.pnl for f in losses) / len(losses)) if losses else 0.0,
            "net_pnl": pnl,
        }
