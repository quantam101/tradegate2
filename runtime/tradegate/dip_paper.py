"""Daily paper run for the dip-buying strategy.

Runs after each US close next to the rotation paper run, but against its
**own Alpaca paper account** (``ALPACA_DIP_PAPER_KEY`` / ``_SECRET``) so the
two strategies can never net or sell each other's positions.

Each run: fetch real daily bars → compute today's buy/sell signals → (with
``--execute`` and keys set) send market orders that queue for the next
open → append a record to ``data/tradegate/dipbuy/YYYY-MM-DD.json``.

Safety: paper endpoint only (enforced by ``AlpacaRebalancer``); only
positions this strategy opened (``state.json`` → ``owned``) are ever sold;
no orders when the newest bar is more than ``max_data_age_days`` old.

An accepted order is not a fill — after-close orders wait for the next open
and can still be cancelled. So every order id is kept in ``state.open``
and reconciled against Alpaca at the start of each run:

* while an order is open, its symbol gets no new signal (no duplicate buys
  across a holiday, no repeated exits);
* a filled sell credits its proceeds to that symbol's slot; a cancelled,
  expired or rejected sell keeps the position owned so the exit retries;
* a filled buy keeps ownership; a cancelled buy releases it with the slot
  untouched.

Each symbol buys with its **own slot balance** (``state.slots``), starting
at capital / len(universe) and updated from real fill proceeds — the same
per-slot reinvestment the backtest uses.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .alpaca_broker import AlpacaPaperBroker
from .dipbuy import DipConfig, signal
from .rotation_paper import AlpacaRebalancer, PlannedOrder, _bars

OUT_DIR = Path("data/tradegate/dipbuy")


def run_dip_paper(capital: float = 1000.0, execute: bool = False,
                  cfg: DipConfig | None = None, out_dir: Path = OUT_DIR,
                  bars_fn=_bars, rebalancer: AlpacaRebalancer | None = None,
                  today: str | None = None, max_data_age_days: int = 4) -> dict:
    cfg = cfg or DipConfig()
    hist, errors = {}, {}
    for s in cfg.universe:
        try:
            hist[s] = bars_fn(s)
        except (OSError, ValueError, KeyError) as e:
            errors[s] = str(e)[:200]
    if not hist:
        raise RuntimeError(f"no market data fetched: {errors}")
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    owned = set(state.get("owned", []))
    asof = max(b[-1]["date"] for b in hist.values() if b)
    today = today or datetime.now(timezone.utc).date().isoformat()
    age = (datetime.fromisoformat(today) - datetime.fromisoformat(asof)).days
    record: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "asof": asof,
                    "capital": capital, "config": cfg.to_dict(),
                    "data_errors": errors, "executed": False, "signals": {}}
    if age > max_data_age_days:
        record["deferred_stale_data"] = {"asof": asof, "age_days": age}
    else:
        rb = None
        slots = {s: float(v) for s, v in state.get("slots", {}).items()}
        for s in cfg.universe:
            slots.setdefault(s, capital / len(cfg.universe))
        open_orders: dict[str, dict] = dict(state.get("open", {}))
        held = set(owned)
        if execute:
            rb = rebalancer or AlpacaRebalancer()
            record["reconciled"] = _reconcile(rb, owned, slots, open_orders)
            positions = rb.positions()
            held = {s for s in owned if s in positions}
            # owned but gone with nothing pending: closed outside this runner
            for s in sorted(owned - set(positions) - set(open_orders)):
                owned.discard(s)
        for s, bars in hist.items():
            if not bars or bars[-1]["date"] != asof or s in open_orders:
                continue  # stale symbol, or an order for it is still working
            sig = signal([b["close"] for b in bars], s in held, cfg)
            if sig:
                record["signals"][s] = sig
        if execute and record["signals"]:
            record["orders"] = []
            for s, sig in sorted(record["signals"].items(), key=lambda kv: kv[1] != "sell"):
                order = (PlannedOrder(s, "sell", 0.0, close_all=True) if sig == "sell"
                         else PlannedOrder(s, "buy", round(slots[s], 2)))
                if order.side == "buy" and order.notional < 1.0:
                    record["orders"].append({**order.__dict__, "accepted": False,
                                             "reason": "slot below $1"})
                    continue
                resp = rb.submit(order)
                ok = bool(resp) and "id" in resp
                record["orders"].append({**order.__dict__, "accepted": ok})
                if ok:
                    open_orders[s] = {"id": str(resp["id"]), "side": order.side}
                    if sig == "buy":
                        owned.add(s)  # released again if the buy is cancelled
            record["executed"] = True
        state["owned"] = sorted(owned)
        state["slots"] = {s: round(v, 6) for s, v in slots.items()}
        state["open"] = open_orders
        state["last_run"] = asof
        state_path.write_text(json.dumps(state, indent=2))
    day = time.strftime("%Y-%m-%d")
    path = out_dir / f"{day}.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.append(record)
    path.write_text(json.dumps(existing, indent=2))
    print(json.dumps({"asof": asof, "signals": record["signals"],
                      "executed": record["executed"]}, indent=2))
    return record


_TERMINAL = {"filled", "canceled", "cancelled", "expired", "rejected",
             "done_for_day", "replaced"}


def _reconcile(rb, owned: set, slots: dict, open_orders: dict) -> list[dict]:
    """Settle tracked orders that reached a final state. Mutates owned,
    slots and open_orders; returns a log of what changed."""
    log = []
    for sym, o in list(open_orders.items()):
        info = rb.order(o["id"])
        if info is None:
            continue  # unknown right now — keep tracking, check next run
        status = str(info.get("status", "")).lower()
        if status not in _TERMINAL:
            continue
        filled_qty = float(info.get("filled_qty") or 0)
        px = float(info.get("filled_avg_price") or 0)
        if o["side"] == "sell":
            if filled_qty > 0:
                slots[sym] = filled_qty * px
                owned.discard(sym)
            # not filled → position still ours; exit re-signals next run
        elif filled_qty <= 0:
            owned.discard(sym)  # buy never filled: release, slot unchanged
        log.append({"symbol": sym, "side": o["side"], "status": status,
                    "filled_qty": filled_qty, "price": px})
        del open_orders[sym]
    return log


def main(argv: list[str]) -> None:
    cap = float(argv[argv.index("--capital") + 1]) if "--capital" in argv else 1000.0
    key = os.getenv("ALPACA_DIP_PAPER_KEY", "")
    secret = os.getenv("ALPACA_DIP_PAPER_SECRET", "")
    execute = "--execute" in argv
    rb = None
    if execute and not (key and secret):
        print("--execute requested but ALPACA_DIP_PAPER_KEY/SECRET not set; running data-only")
        execute = False
    if execute:
        rb = AlpacaRebalancer(AlpacaPaperBroker(key=key, secret=secret))
    run_dip_paper(capital=cap, execute=execute, rebalancer=rb)
