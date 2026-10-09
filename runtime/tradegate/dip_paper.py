"""Daily paper run for the dip-buying strategy.

Runs after each US close next to the rotation paper run, but against its
**own Alpaca paper account** (``ALPACA_DIP_PAPER_KEY`` / ``_SECRET``) so the
two strategies can never net or sell each other's positions.

Each run: fetch real daily bars → compute today's buy/sell signals → (with
``--execute`` and keys set) send market orders that queue for the next
open → append a record to ``data/tradegate/dipbuy/YYYY-MM-DD.json``.

Safety: paper endpoint only (enforced by ``AlpacaRebalancer``); only
positions this strategy opened (``state.json`` → ``owned``) are ever sold;
no orders when the newest bar is more than ``max_data_age_days`` old; a
rejected order simply re-signals on the next run.
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
        held = set(owned)
        if execute:
            rb = rebalancer or AlpacaRebalancer()
            held = {s for s in rb.positions() if s in owned}
        for s, bars in hist.items():
            if not bars or bars[-1]["date"] != asof:
                continue  # stale symbol: no signal today
            sig = signal([b["close"] for b in bars], s in held, cfg)
            if sig:
                record["signals"][s] = sig
        if execute and record["signals"]:
            budget = min(capital, rb.equity())
            slot = budget / len(cfg.universe)
            record["orders"] = []
            for s, sig in sorted(record["signals"].items(), key=lambda kv: kv[1] != "sell"):
                order = (PlannedOrder(s, "sell", 0.0, close_all=True) if sig == "sell"
                         else PlannedOrder(s, "buy", slot))
                ok = rb.submit(order) is not None
                record["orders"].append({**order.__dict__, "accepted": ok})
                if ok:
                    (owned.discard if sig == "sell" else owned.add)(s)
            record["executed"] = True
            record["budget"] = budget
        state["owned"] = sorted(owned)
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
