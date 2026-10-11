"""Short-term dip buying (RSI(2) mean reversion) — portfolio-level, daily bars.

Rules (Connors' published defaults, deliberately *not* tuned — the
rotation study showed tuning is overfitting):

* **Enter** a symbol at the next open when its close is above its 200-day
  SMA (only buy dips in uptrends) and its 2-day RSI is below 10 (a sharp
  two-day sell-off).
* **Exit** at the next open once the close is back above its 5-day SMA.
* Capital is split into equal slots, one per symbol, so a single dip can't
  take the whole account. Idle slots sit in cash.

No look-ahead: signals use closes through day *t*; fills happen at day
*t+1*'s open. Every traded dollar pays ``cost_bps``. This strategy trades
far more often than the monthly rotation, so it is much more sensitive to
costs — see docs/tradegate-dipbuy.md.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class DipConfig:
    universe: tuple[str, ...] = ("SPY", "QQQ", "IWM", "IBIT")
    rsi_period: int = 2
    rsi_entry: float = 10.0
    trend_sma: int = 200
    exit_sma: int = 5
    cost_bps: float = 5.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["universe"] = list(self.universe)
        return d


def rsi(closes: list[float], period: int) -> float | None:
    """Wilder-style simple RSI over the last ``period`` changes."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-period - 1:-1], closes[-period:]):
        ch = b - a
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def signal(closes: list[float], holding: bool, cfg: DipConfig) -> str | None:
    """'buy', 'sell' or None from closes through today."""
    if len(closes) < max(cfg.trend_sma, cfg.exit_sma, cfg.rsi_period + 1):
        return None
    if holding:
        return "sell" if closes[-1] > sum(closes[-cfg.exit_sma:]) / cfg.exit_sma else None
    trend = sum(closes[-cfg.trend_sma:]) / cfg.trend_sma
    r = rsi(closes, cfg.rsi_period)
    if closes[-1] > trend and r is not None and r < cfg.rsi_entry:
        return "buy"
    return None


@dataclass
class DipResult:
    start_value: float
    end_value: float
    equity: list[tuple[str, float]] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)

    def metrics(self) -> dict:
        vals = [v for _, v in self.equity]
        rets = [b / a - 1 for a, b in zip(vals, vals[1:]) if a > 0]
        peak, mdd = (vals[0] if vals else 0.0), 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak if peak else 0.0)
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        closed = [t for t in self.trades if t["side"] == "SELL"]
        wins = [t for t in closed if t["pnl"] > 0]
        return {
            "start_value": round(self.start_value, 2),
            "end_value": round(self.end_value, 2),
            "net_pnl": round(self.end_value - self.start_value, 2),
            "roi": self.end_value / self.start_value - 1,
            "max_drawdown": mdd,
            "sharpe": (statistics.mean(rets) / sd * math.sqrt(252)) if sd > 0 else 0.0,
            "round_trips": len(closed),
            "win_rate": len(wins) / len(closed) if closed else 0.0,
        }


def run_dipbuy(data: dict[str, list[dict]], cfg: DipConfig | None = None,
               capital: float = 1000.0, start: str | None = None,
               end: str | None = None) -> DipResult:
    """Simulate from ``start`` with ``capital`` split across ``cfg.universe``.

    History before ``start`` feeds the indicators only. A position still
    open at ``end`` is marked at its last close (not force-sold).
    """
    cfg = cfg or DipConfig()
    syms = [s for s in cfg.universe if s in data]
    if not syms:
        raise ValueError("none of the universe symbols are in the data")
    idx = {s: {b["date"]: i for i, b in enumerate(data[s])} for s in syms}
    dates = sorted({b["date"] for s in syms for b in data[s]})
    if end:
        dates = [d for d in dates if d <= end]
    trading = [d for d in dates if not start or d >= start]
    if len(trading) < 2:
        raise ValueError("not enough trading days in window")

    slot = capital / len(syms)
    cash = {s: slot for s in syms}       # each symbol trades only its slot
    units: dict[str, float] = {}
    basis: dict[str, float] = {}
    pending: dict[str, str] = {}
    last_close: dict[str, float] = {}
    res = DipResult(start_value=capital, end_value=capital)
    fee = cfg.cost_bps / 1e4

    for day in trading:
        # 1) fill yesterday's signals at today's open
        for s, side in list(pending.items()):
            i = idx[s].get(day)
            if i is None:
                continue  # no bar today: keep the order pending
            px = data[s][i]["open"]
            if side == "buy" and s not in units:
                q = cash[s] / (px * (1 + fee))
                cash[s] -= q * px * (1 + fee)
                units[s], basis[s] = q, px * (1 + fee)
                res.trades.append({"date": day, "symbol": s, "side": "BUY",
                                   "qty": q, "price": px})
            elif side == "sell" and s in units:
                q = units.pop(s)
                proceeds = q * px * (1 - fee)
                cash[s] += proceeds
                res.trades.append({"date": day, "symbol": s, "side": "SELL", "qty": q,
                                   "price": px, "pnl": proceeds - q * basis.pop(s)})
            del pending[s]
        # 2) mark to market
        for s in syms:
            i = idx[s].get(day)
            if i is not None:
                last_close[s] = data[s][i]["close"]
        value = sum(cash.values()) + sum(q * last_close[s] for s, q in units.items())
        res.equity.append((day, value))
        # 3) signals from closes through today
        for s in syms:
            i = idx[s].get(day)
            if i is None or s in pending:
                continue
            closes = [b["close"] for b in data[s][:i + 1]]
            sig = signal(closes, s in units, cfg)
            if sig:
                pending[s] = sig
    res.end_value = res.equity[-1][1]
    return res
