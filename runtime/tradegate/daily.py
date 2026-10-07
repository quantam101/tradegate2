"""Daily paper run on real market data — the honest pre-live gate.

For each symbol: fetch ~1y of real daily bars, stream them through the
full 9-agent mesh + PaperBroker, then report metrics *next to* the
buy-and-hold benchmark for the same window. A strategy that can't beat
buy-and-hold on real data is worth exactly nothing — this report says so.

Results append to ``data/tradegate/daily/YYYY-MM-DD.json`` (one record per
run) so the GitHub cron builds a durable, auditable history.

Usage:
    python -m runtime.tradegate daily --symbols SPY,QQQ --capital 10000
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .backtest import run_backtest
from .config import EngineConfig
from .daily_feed import bars_to_ticks, buy_hold_return, fetch_bars

log = logging.getLogger(__name__)

LEDGER_DIR = Path("data/tradegate/daily")


def run_daily(symbols: list[str], capital: float = 10000.0,
              config: EngineConfig | None = None,
              ledger_dir: Path = LEDGER_DIR) -> dict:
    """Backtest the mesh on real daily bars for each symbol and append the
    results to today's ledger. Returns the full report dict."""
    cfg = config or EngineConfig()
    per_symbol = []
    for sym in symbols:
        sym = sym.strip().upper()
        try:
            bars = fetch_bars(sym)
        except (OSError, ValueError, KeyError) as e:
            per_symbol.append({"symbol": sym, "error": str(e)[:200]})
            log.warning("fetch failed for %s: %s", sym, e)
            continue
        ticks = bars_to_ticks(sym, bars)
        metrics = run_backtest(ticks, cfg, initial_capital=capital)
        bh = buy_hold_return(bars)
        per_symbol.append({
            "symbol": sym,
            "bars": len(bars),
            "window": {"from": datetime.fromtimestamp(bars[0].ts, timezone.utc).date().isoformat(),
                       "to": datetime.fromtimestamp(bars[-1].ts, timezone.utc).date().isoformat()},
            "strategy": metrics,
            "buy_hold_roi": round(bh, 6),
            "beats_benchmark": metrics["roi"] > bh,
        })

    traded = [s for s in per_symbol if "strategy" in s]
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "capital": capital,
        "config_version": cfg.version,
        "symbols": per_symbol,
        "summary": {
            "symbols_ok": len(traded),
            "total_trades": sum(s["strategy"]["trades"] for s in traded),
            "mean_strategy_roi": (sum(s["strategy"]["roi"] for s in traded) / len(traded)
                                  if traded else 0.0),
            "mean_benchmark_roi": (sum(s["buy_hold_roi"] for s in traded) / len(traded)
                                   if traded else 0.0),
            "beat_benchmark_count": sum(1 for s in traded if s["beats_benchmark"]),
        },
    }
    report["summary"]["edge_vs_benchmark"] = round(
        report["summary"]["mean_strategy_roi"] - report["summary"]["mean_benchmark_roi"], 6)

    ledger_dir.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    out = ledger_dir / f"{day}.json"
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text())
        except (OSError, ValueError):
            existing = []
    existing.append(report)
    out.write_text(json.dumps(existing, indent=2))
    print(json.dumps(report["summary"], indent=2))
    print(f"ledger → {out}")
    return report
