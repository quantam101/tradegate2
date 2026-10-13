"""Cost-sensitivity check — does the validated edge survive real costs?

Re-runs the existing backtest harness on real daily bars at several
transaction-cost levels (default 5, 10, 20 bps per traded dollar —
commission + slippage combined) and prints a per-strategy table. Both
strategies charge ``cost_bps`` on every traded dollar inside
``run_rotation`` / ``run_dipbuy`` — no special-cased math here.

"Survives" is defined honestly, not generously: ``roi > 0`` at the cost
level. Whether it still beats buy-and-hold is reported separately so a
positive-but-losing-to-the-index edge is visible, not hidden.

CLI: ``python -m runtime.tradegate cost-check [--capital 1000]
      [--costs 5,10,20]``
Exit code 1 when data can't be fetched or the edge fails at 20bps, so CI
can gate on it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .daily_feed import fetch_bars
from .dipbuy import DipConfig, run_dipbuy
from .rotation import RotationConfig, buy_and_hold, run_rotation
from .rotation_paper import UNIVERSE as ROTATION_UNIVERSE

OUT_DIR = Path("data/tradegate/truth")
DEFAULT_COSTS = (5.0, 10.0, 20.0)


def _bars(symbol: str, range_: str = "2y") -> list[dict]:
    return [{"date": datetime.fromtimestamp(b.ts, timezone.utc).date().isoformat(),
             "open": b.open, "high": b.high, "low": b.low, "close": b.close}
            for b in fetch_bars(symbol, range_)]


def run_cost_check(capital: float = 1000.0,
                   costs: tuple[float, ...] = DEFAULT_COSTS,
                   bars_fn=_bars) -> dict:
    """{strategy: {cost_bps: metrics}} plus a per-cost survival verdict."""
    report: dict = {"run_at": datetime.now(timezone.utc).isoformat(),
                    "capital": capital, "strategies": {}, "errors": {}}

    rot_hist, dip_hist = {}, {}
    for s in ROTATION_UNIVERSE:
        try:
            rot_hist[s] = bars_fn(s)
        except (OSError, ValueError, KeyError) as e:
            report["errors"][s] = str(e)[:200]
    dip_cfg = DipConfig()
    for s in dip_cfg.universe:
        try:
            dip_hist[s] = bars_fn(s)
        except (OSError, ValueError, KeyError) as e:
            report["errors"][s] = str(e)[:200]
    if not rot_hist and not dip_hist:
        raise RuntimeError(f"no market data fetched: {report['errors']}")

    def _window(hist):
        dates = sorted(b[-1]["date"] for b in hist.values() if b)
        return {"to": max(dates)} if dates else {}

    if rot_hist:
        first = min(b[0]["date"] for b in rot_hist.values() if b)
        last = max(b[-1]["date"] for b in rot_hist.values() if b)
        rows = {}
        for c in costs:
            cfg = RotationConfig(**{**RotationConfig().to_dict(), "cost_bps": c})
            m = run_rotation(rot_hist, cfg, capital).metrics()
            m["edge_survives"] = m["roi"] > 0
            rows[f"{c:g}"] = m
        report["strategies"]["rotation"] = {
            "window": {"from": first, "to": last},
            "buy_hold_roi": buy_and_hold(rot_hist, list(rot_hist), first, last),
            "by_cost_bps": rows}
    if dip_hist:
        first = min(b[0]["date"] for b in dip_hist.values() if b)
        last = max(b[-1]["date"] for b in dip_hist.values() if b)
        rows = {}
        for c in costs:
            cfg = DipConfig(**{**dip_cfg.to_dict(), "cost_bps": c})
            m = run_dipbuy(dip_hist, cfg, capital).metrics()
            m["edge_survives"] = m["roi"] > 0
            rows[f"{c:g}"] = m
        report["strategies"]["dipbuy"] = {
            "window": {"from": first, "to": last},
            "by_cost_bps": rows}
    report["survives_at_max_cost"] = all(
        rows[f"{max(costs):g}"]["edge_survives"]
        for s in report["strategies"].values()
        for rows in [s["by_cost_bps"]])
    return report


def _print_table(report: dict) -> None:
    for name, strat in report["strategies"].items():
        print(f"\n{name}  window {strat['window']['from']} → {strat['window']['to']}"
              + (f"  buy&hold roi={strat['buy_hold_roi']:+.2%}"
                 if "buy_hold_roi" in strat else ""))
        print(f"  {'cost_bps':>9} {'roi':>9} {'sharpe':>7} {'max_dd':>7} "
              f"{'trades':>7} {'win_rate':>8} survives")
        for cost, m in strat["by_cost_bps"].items():
            print(f"  {cost:>9} {m['roi']:>+9.2%} {m['sharpe']:>7.2f} "
                  f"{m['max_drawdown']:>7.2%} {m.get('trades', m.get('round_trips', 0)):>7} "
                  f"{m['win_rate']:>8.2%} {'YES' if m['edge_survives'] else 'NO'}")
    print(f"\nsurvives_at_max_cost: {report['survives_at_max_cost']}")


def main(argv: list[str]) -> None:
    cap = float(argv[argv.index("--capital") + 1]) if "--capital" in argv else 1000.0
    costs = DEFAULT_COSTS
    if "--costs" in argv:
        costs = tuple(float(c) for c in
                      argv[argv.index("--costs") + 1].split(","))
    report = run_cost_check(capital=cap, costs=costs)
    _print_table(report)
    out = OUT_DIR / f"cost-check-{datetime.now(timezone.utc).date()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nreport → {out}")
    if not report["survives_at_max_cost"]:
        sys.exit(1)
