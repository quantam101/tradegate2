"""Multi-asset momentum rotation — portfolio-level, daily bars.

Why this exists: the tick-microstructure mesh (agents.py) has no edge on
daily data — its depth/CVD inputs are placeholders there, and real-data
backtests show it losing to buy-and-hold across equities, gold, bonds,
crypto ETFs and currency ETFs. This module implements the two most
replicated return anomalies in the literature instead:

* **Time-series momentum / trend filter** (Moskowitz, Ooi & Pedersen 2012;
  Faber 2007): only hold an asset while it trades above its moving average.
* **Cross-sectional momentum with an absolute-momentum gate** (Antonacci,
  "Dual Momentum"): rank assets by trailing return, hold the top K, and sit
  in cash rather than hold an asset whose own trailing return is negative.

Weights are optionally inverse-volatility so a Bitcoin ETF doesn't swamp
a currency ETF.

No look-ahead, by construction: the target portfolio is computed from
closes up to and including day *t*, and trades fill at day *t+1*'s open.
Every traded dollar pays ``cost_bps``. An asset is only eligible once it
has ``lookback`` bars of its own history.

Usage:
    python -m runtime.tradegate rotation --csv prices.csv --capital 1000 \
        --start 2026-04-09
CSV columns: symbol,date,open,high,low,close,volume
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RotationConfig:
    # Defaults chosen on Apr 2024 – Apr 2026 data only (best median Sharpe
    # and smallest drawdown across a 144-config grid), then forward-tested
    # untouched on Apr – Oct 2026. See docs/tradegate-rotation.md.
    lookback: int = 189          # trailing-return window for ranking (bars)
    top_k: int = 4               # assets held at once
    sma: int = 100               # trend filter: close must exceed this SMA
    use_sma: bool = True
    abs_momentum: bool = True    # require trailing return > 0
    rebalance_every: int = 21    # bars between rebalances (21 ≈ monthly)
    inverse_vol: bool = True     # weight by 1/vol instead of equally
    vol_window: int = 63
    cost_bps: float = 5.0        # per traded dollar (commission+slippage)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RotationResult:
    start_value: float
    end_value: float
    equity: list[tuple[str, float]] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    holdings: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def roi(self) -> float:
        return self.end_value / self.start_value - 1

    def metrics(self) -> dict:
        vals = [v for _, v in self.equity]
        rets = [b / a - 1 for a, b in zip(vals, vals[1:]) if a > 0]
        peak, mdd = vals[0] if vals else 0, 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak if peak else 0)
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        sharpe = (statistics.mean(rets) / sd * math.sqrt(252)) if sd > 0 else 0.0
        closed = [t for t in self.trades if t["side"] == "SELL" and "pnl" in t]
        wins = [t for t in closed if t["pnl"] > 0]
        return {
            "start_value": round(self.start_value, 2),
            "end_value": round(self.end_value, 2),
            "net_pnl": round(self.end_value - self.start_value, 2),
            "roi": self.roi,
            "max_drawdown": mdd,
            "sharpe": sharpe,
            "round_trips": len(closed),
            "win_rate": len(wins) / len(closed) if closed else 0.0,
            "trades": len(self.trades),
        }


def load_csv(path: Path) -> dict[str, list[dict]]:
    """symbol -> list of bars (dict with date/open/high/low/close), sorted."""
    out: dict[str, list[dict]] = {}
    with Path(path).open() as f:
        for r in csv.DictReader(f):
            out.setdefault(r["symbol"].upper(), []).append({
                "date": r["date"][:10], "open": float(r["open"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"])})
    for bars in out.values():
        bars.sort(key=lambda b: b["date"])
    return out


def _target_weights(hist: dict[str, list[dict]], cfg: RotationConfig) -> dict[str, float]:
    """Target portfolio from closes known so far (each list ends at day t)."""
    scored = []
    for sym, bars in hist.items():
        need = max(cfg.lookback, cfg.sma if cfg.use_sma else 0, cfg.vol_window) + 1
        if len(bars) < need:
            continue
        closes = [b["close"] for b in bars]
        mom = closes[-1] / closes[-1 - cfg.lookback] - 1
        if cfg.abs_momentum and mom <= 0:
            continue
        if cfg.use_sma and closes[-1] <= sum(closes[-cfg.sma:]) / cfg.sma:
            continue
        rets = [b / a - 1 for a, b in zip(closes[-cfg.vol_window - 1:-1],
                                         closes[-cfg.vol_window:])]
        vol = statistics.pstdev(rets) or 1e-9
        scored.append((mom, sym, vol))
    scored.sort(reverse=True)
    picks = scored[:cfg.top_k]
    if not picks:
        return {}
    raw = {s: (1 / v if cfg.inverse_vol else 1.0) for _, s, v in picks}
    tot = sum(raw.values())
    return {s: w / tot for s, w in raw.items()}


def run_rotation(data: dict[str, list[dict]], cfg: RotationConfig | None = None,
                 capital: float = 1000.0, start: str | None = None,
                 end: str | None = None) -> RotationResult:
    """Simulate from ``start`` (inclusive) with ``capital`` in cash.

    History before ``start`` is used for signals only — no trades occur
    before it, so the result is a clean forward test from that date.
    """
    cfg = cfg or RotationConfig()
    dates = sorted({b["date"] for bars in data.values() for b in bars})
    if end:
        dates = [d for d in dates if d <= end]
    idx = {s: {b["date"]: i for i, b in enumerate(bars)} for s, bars in data.items()}
    trading = [d for d in dates if not start or d >= start]
    if len(trading) < 2:
        raise ValueError("not enough trading days in window")

    cash, units = capital, {}
    cost_basis: dict[str, float] = {}
    res = RotationResult(start_value=capital, end_value=capital)
    pending: dict[str, float] | None = None
    since_rebal = cfg.rebalance_every  # rebalance on the first eligible close

    def px(sym: str, day: str, key: str) -> float | None:
        i = idx[sym].get(day)
        return data[sym][i][key] if i is not None else None

    last_close: dict[str, float] = {}
    for day in trading:
        # 1) execute yesterday's target at today's open
        if pending is not None:
            opens = {s: px(s, day, "open") for s in set(units) | set(pending)}
            if all(v is not None for v in opens.values()):
                value = cash + sum(u * opens[s] for s, u in units.items())
                for s in list(units):  # sells first
                    tgt_units = pending.get(s, 0) * value / opens[s]
                    if tgt_units < units[s] - 1e-12:
                        q = units[s] - tgt_units
                        notional = q * opens[s]
                        fee = notional * cfg.cost_bps / 1e4
                        cash += notional - fee
                        pnl = (opens[s] - cost_basis[s]) * q - fee
                        res.trades.append({"date": day, "symbol": s, "side": "SELL",
                                           "qty": q, "price": opens[s], "pnl": pnl})
                        units[s] = tgt_units
                        if units[s] <= 1e-12:
                            del units[s]
                            cost_basis.pop(s, None)
                for s, w in pending.items():  # then buys
                    tgt_units = w * value / opens[s]
                    have = units.get(s, 0.0)
                    if tgt_units > have + 1e-12:
                        q = tgt_units - have
                        notional = q * opens[s]
                        fee = notional * cfg.cost_bps / 1e4
                        if notional + fee > cash:
                            q = cash / (opens[s] * (1 + cfg.cost_bps / 1e4))
                            notional, fee = q * opens[s], q * opens[s] * cfg.cost_bps / 1e4
                        if q <= 0:
                            continue
                        cash -= notional + fee
                        cost_basis[s] = ((cost_basis.get(s, 0) * have + notional + fee)
                                         / (have + q))
                        units[s] = have + q
                        res.trades.append({"date": day, "symbol": s, "side": "BUY",
                                           "qty": q, "price": opens[s]})
                res.holdings.append((day, dict(pending)))
                pending = None
        # 2) mark to market at today's close
        for s in data:
            c = px(s, day, "close")
            if c is not None:
                last_close[s] = c
        value = cash + sum(u * last_close[s] for s, u in units.items())
        res.equity.append((day, value))
        # 3) decide tomorrow's target from closes through today
        since_rebal += 1
        if since_rebal >= cfg.rebalance_every:
            hist = {s: data[s][:idx[s][day] + 1] for s in data if day in idx[s]}
            pending = _target_weights(hist, cfg)
            since_rebal = 0
    res.end_value = res.equity[-1][1]
    return res


def buy_and_hold(data: dict[str, list[dict]], symbols: list[str], start: str,
                 end: str | None = None) -> float:
    """Equal-weight buy at first open on/after ``start``, mark at last close."""
    rets = []
    for s in symbols:
        bars = [b for b in data[s] if b["date"] >= start and (not end or b["date"] <= end)]
        if len(bars) >= 2:
            rets.append(bars[-1]["close"] / bars[0]["open"] - 1)
    return sum(rets) / len(rets) if rets else 0.0
