"""Daily paper run for the momentum rotation — the pre-live gate.

Each weekday after the US close:

1. Fetch ~2y of real daily bars for the universe (Yahoo → Stooq fallback).
2. Decide whether today is a rebalance day (every ``rebalance_every`` bars
   since the last rebalance, tracked in ``state.json``).
3. On a rebalance day compute the target portfolio from today's closes.
4. With ``--execute`` and Alpaca *paper* keys set, submit the orders. Market
   orders sent after the close queue for the next open, which matches the
   backtest's next-open fill assumption.
5. Append a JSON record to ``data/tradegate/rotation/YYYY-MM-DD.json`` so
   the paper track record is durable and auditable in git.

Paper only: the order path is hard-wired to ``paper-api.alpaca.markets``
and refuses any other base URL. ``--capital`` caps the budget so the paper
account mirrors the $1,000 backtests even if it holds more.

Safety rules:
* Only symbols the rotation itself bought (``state.json`` → ``owned``) are
  ever sold; other positions in the account are left alone. A dedicated
  paper account is still recommended so overlapping symbols can't mix.
* Orders are placed only from the latest completed session's bars; if the
  newest bar is more than ``max_data_age_days`` old the run defers.
* The rebalance date advances only when every order was accepted, so a
  rejected order is retried the next day instead of waiting a full cycle.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .alpaca_broker import PAPER_BASE, AlpacaPaperBroker
from .daily_feed import fetch_bars
from .rotation import RotationConfig, _target_weights

log = logging.getLogger(__name__)

UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT", "IBIT", "ETHA", "FXE", "FXY", "UUP"]
OUT_DIR = Path("data/tradegate/rotation")


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: str          # "buy" | "sell"
    notional: float    # dollars
    close_all: bool = False


def plan_rebalance(budget: float, positions: dict[str, float],
                   weights: dict[str, float], min_trade: float = 1.0,
                   drift_tolerance: float = 0.02) -> list[PlannedOrder]:
    """Orders that move ``positions`` (symbol → market value $) to
    ``weights`` × ``budget``. Sells come first so buys are funded. Trades
    smaller than ``min_trade`` dollars or within ``drift_tolerance`` of the
    budget are skipped to avoid churning on noise."""
    orders: list[PlannedOrder] = []
    syms = set(positions) | set(weights)
    for s in sorted(syms):
        have = positions.get(s, 0.0)
        want = weights.get(s, 0.0) * budget
        delta = want - have
        if want <= 0 and have > 0:
            orders.append(PlannedOrder(s, "sell", have, close_all=True))
        elif abs(delta) >= max(min_trade, drift_tolerance * budget):
            orders.append(PlannedOrder(s, "buy" if delta > 0 else "sell", abs(delta)))
    return sorted(orders, key=lambda o: o.side != "sell")


def is_rebalance_day(bar_dates: list[str], last_rebalance: str | None,
                     every: int) -> bool:
    if not last_rebalance:
        return True
    return sum(1 for d in bar_dates if d > last_rebalance) >= every


def _bars(symbol: str) -> list[dict]:
    return [{"date": datetime.fromtimestamp(b.ts, timezone.utc).date().isoformat(),
             "open": b.open, "high": b.high, "low": b.low, "close": b.close}
            for b in fetch_bars(symbol, "2y")]


class AlpacaRebalancer:
    """Minimal account/positions/notional-order client on the paper API."""

    def __init__(self, broker: AlpacaPaperBroker | None = None):
        self.broker = broker or AlpacaPaperBroker()
        if self.broker.base != PAPER_BASE:
            raise ValueError("rotation paper runner only trades the Alpaca paper API")

    def equity(self) -> float:
        return float(self.broker._req("GET", "/v2/account")["equity"])

    def positions(self) -> dict[str, float]:
        rows = self.broker._req("GET", "/v2/positions") or []
        return {r["symbol"]: float(r["market_value"]) for r in rows}

    def order(self, order_id: str) -> dict | None:
        """Current state of one order (status, filled_qty, filled_avg_price)."""
        return self.broker._req("GET", f"/v2/orders/{urllib.parse.quote(order_id)}")

    def submit(self, o: PlannedOrder) -> dict | None:
        if o.close_all:
            return self.broker._req("DELETE",
                                    f"/v2/positions/{urllib.parse.quote(o.symbol)}")
        return self.broker._req("POST", "/v2/orders", {
            "symbol": o.symbol, "side": o.side, "type": "market",
            "time_in_force": "day", "notional": f"{o.notional:.2f}"})


def run_rotation_paper(capital: float = 1000.0, execute: bool = False,
                       universe: list[str] | None = None,
                       cfg: RotationConfig | None = None,
                       out_dir: Path = OUT_DIR,
                       bars_fn=_bars, rebalancer: AlpacaRebalancer | None = None,
                       today: str | None = None, max_data_age_days: int = 4) -> dict:
    cfg = cfg or RotationConfig()
    universe = universe or UNIVERSE
    hist, errors = {}, {}
    for s in universe:
        try:
            hist[s] = bars_fn(s)
        except (OSError, ValueError, KeyError) as e:
            errors[s] = str(e)[:200]
    if not hist:
        raise RuntimeError(f"no market data fetched: {errors}")
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    # the newest observed session, not the longest history
    asof = max(b[-1]["date"] for b in hist.values() if b)
    dates = sorted({b["date"] for bars in hist.values() for b in bars})
    today = today or datetime.now(timezone.utc).date().isoformat()
    age = (datetime.fromisoformat(today) - datetime.fromisoformat(asof)).days
    record: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "asof": asof,
                    "capital": capital, "config": cfg.to_dict(),
                    "data_errors": errors, "executed": False}
    if age > max_data_age_days:
        record["deferred_stale_data"] = {"asof": asof, "age_days": age}
        rebalance = False
    else:
        rebalance = is_rebalance_day(dates, state.get("last_rebalance"),
                                     cfg.rebalance_every)
    record["rebalance_day"] = rebalance
    if rebalance:
        # every symbol in the target must have today's close (no stale data)
        fresh = {s: b for s, b in hist.items() if b and b[-1]["date"] == asof}
        weights = _target_weights(fresh, cfg)
        record["target_weights"] = {s: round(w, 6) for s, w in weights.items()}
        record["closes"] = {s: fresh[s][-1]["close"] for s in fresh}
        deferred = False
        if execute:
            rb = rebalancer or AlpacaRebalancer()
            positions = rb.positions()
            # a symbol stays owned until its position is actually gone: an
            # accepted sell can still be cancelled before the open
            owned = {s for s in state.get("owned", []) if s in positions}
            # never touch positions the rotation didn't open
            held = {s: v for s, v in positions.items() if s in owned}
            unpriced = sorted(s for s in held if s not in fresh)
            if unpriced:
                # a missing bar is unknown, not a sell signal: retry tomorrow
                record["deferred_unpriced_holdings"] = unpriced
                deferred = True
            else:
                budget = min(capital, rb.equity())
                orders = plan_rebalance(budget, held, weights)
                record["orders"] = []
                for o in orders:
                    resp = rb.submit(o)
                    record["orders"].append({**o.__dict__,
                                             "accepted": bool(resp is not None)})
                record["executed"] = True
                record["budget"] = budget
                rejected = [o["symbol"] for o in record["orders"] if not o["accepted"]]
                accepted = {o["symbol"]: o for o in record["orders"] if o["accepted"]}
                # ownership: add accepted buys; exits are released only once
                # the position disappears (pruned at the start of a run)
                for sym, o in accepted.items():
                    if o["side"] == "buy" and not o["close_all"]:
                        owned.add(sym)
                state["owned"] = sorted(owned)
                if rejected:
                    # retry tomorrow rather than wait a full cycle
                    record["rejected_orders"] = rejected
                    deferred = True
                    state_path.write_text(json.dumps(state, indent=2))
        if not deferred:
            state["last_rebalance"] = asof
            state_path.write_text(json.dumps(state, indent=2))
    day = time.strftime("%Y-%m-%d")
    path = out_dir / f"{day}.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.append(record)
    path.write_text(json.dumps(existing, indent=2))
    print(json.dumps({k: record[k] for k in ("asof", "rebalance_day", "executed")
                      if k in record} | {"target_weights": record.get("target_weights")},
                     indent=2))
    return record


def main(argv: list[str]) -> None:
    cap = float(argv[argv.index("--capital") + 1]) if "--capital" in argv else 1000.0
    execute = "--execute" in argv
    if execute and not (os.getenv("ALPACA_PAPER_KEY") and os.getenv("ALPACA_PAPER_SECRET")):
        print("--execute requested but ALPACA_PAPER_KEY/SECRET not set; running data-only")
        execute = False
    run_rotation_paper(capital=cap, execute=execute)
