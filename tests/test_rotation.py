import math

import pytest

from runtime.tradegate.rotation import (
    RotationConfig,
    _target_weights,
    buy_and_hold,
    run_rotation,
)


def _series(sym, n, start=100.0, drift=0.001, start_day=0):
    bars, px = [], start
    for i in range(n):
        px *= 1 + drift
        d = f"2025-{1 + (start_day + i) // 28:02d}-{1 + (start_day + i) % 28:02d}"
        bars.append({"date": d, "open": px, "high": px * 1.01,
                     "low": px * 0.99, "close": px})
    return bars


CFG = RotationConfig(lookback=20, top_k=2, sma=10, vol_window=10,
                     rebalance_every=5, cost_bps=0.0)


def test_picks_strongest_positive_momentum():
    hist = {"UP": _series("UP", 40, drift=0.01),
            "MID": _series("MID", 40, drift=0.003),
            "DOWN": _series("DOWN", 40, drift=-0.01)}
    w = _target_weights(hist, CFG)
    assert set(w) == {"UP", "MID"}
    assert sum(w.values()) == pytest.approx(1.0)


def test_goes_to_cash_when_everything_falls():
    hist = {"A": _series("A", 40, drift=-0.005), "B": _series("B", 40, drift=-0.01)}
    assert _target_weights(hist, CFG) == {}


def test_asset_without_enough_history_is_ineligible():
    hist = {"OLD": _series("OLD", 40, drift=0.002),
            "NEW": _series("NEW", 5, drift=0.05)}
    assert set(_target_weights(hist, CFG)) == {"OLD"}


def test_no_lookahead_future_bars_do_not_change_past_decisions():
    data = {"A": _series("A", 120, drift=0.004), "B": _series("B", 120, drift=0.002)}
    full = run_rotation(data, CFG, 1000.0)
    cut = {s: b[:80] for s, b in data.items()}
    part = run_rotation(cut, CFG, 1000.0)
    upto = part.equity[-1][0]
    assert dict(full.equity)[upto] == pytest.approx(part.equity[-1][1])


def test_trades_fill_next_open_and_costs_reduce_value():
    data = {"A": _series("A", 80, drift=0.004)}
    free = run_rotation(data, CFG, 1000.0)
    paid = run_rotation(data, RotationConfig(**{**CFG.to_dict(), "cost_bps": 50.0}), 1000.0)
    assert paid.end_value < free.end_value
    first_buy = next(t for t in free.trades if t["side"] == "BUY")
    executed = next(d for d, w in free.holdings if w)  # first non-cash target
    assert first_buy["date"] == executed
    dates = [b["date"] for b in data["A"]]
    # the target was computed from the prior day's close, never same-day
    assert dates.index(executed) >= CFG.lookback + 1
    bar = next(b for b in data["A"] if b["date"] == first_buy["date"])
    assert first_buy["price"] == bar["open"]


def test_start_date_trades_only_from_start_with_full_capital():
    data = {"A": _series("A", 100, drift=0.003)}
    start = data["A"][60]["date"]
    res = run_rotation(data, CFG, 1000.0, start=start)
    assert res.equity[0][0] == start
    assert all(t["date"] >= start for t in res.trades)
    assert math.isclose(res.start_value, 1000.0)


def test_buy_and_hold_equal_weight():
    data = {"A": _series("A", 30, drift=0.01), "B": _series("B", 30, drift=0.0)}
    r = buy_and_hold(data, ["A", "B"], data["A"][0]["date"])
    a = data["A"][-1]["close"] / data["A"][0]["open"] - 1
    assert r == pytest.approx(a / 2)


def _drop(bars, dates):
    return [b for b in bars if b["date"] not in dates]


def test_unfilled_target_waits_for_missing_open_and_is_not_replaced():
    a = _series("A", 80, drift=0.004)
    b = _series("B", 80, drift=0.002)
    full = run_rotation({"A": a, "B": b}, CFG, 1000.0)
    first_exec = next(d for d, w in full.holdings if w)
    # B has no bar on the day the first target would fill
    gap = run_rotation({"A": a, "B": _drop(b, {first_exec})}, CFG, 1000.0)
    exec_gap = next(d for d, w in gap.holdings if w)
    dates = [x["date"] for x in a]
    assert dates.index(exec_gap) == dates.index(first_exec) + 1
    assert next(w for d, w in gap.holdings if w) == next(w for d, w in full.holdings if w)


def test_rebalance_deferred_when_held_symbol_has_no_close():
    a = _series("A", 120, drift=0.004)
    b = _series("B", 120, drift=0.003)
    base = run_rotation({"A": a, "B": b}, CFG, 1000.0)
    targets = [d for d, w in base.holdings if w]
    # decision day for the 2nd target is the trading day before it executes
    dates = [x["date"] for x in a]
    decide = dates[dates.index(targets[1]) - 1]
    res = run_rotation({"A": a, "B": _drop(b, {decide})}, CFG, 1000.0)
    # B stays in every target: a missing bar never reads as failed momentum
    live = [w for d, w in res.holdings if w]
    assert live and all("B" in w for w in live)


def test_discontinued_holding_fails_instead_of_stale_valuation():
    a = _series("A", 100, drift=0.002)
    b = _series("B", 100, drift=0.006)
    with pytest.raises(ValueError, match="no price"):
        run_rotation({"A": a, "B": b[:60]}, CFG, 1000.0)


def test_short_gap_in_held_symbol_is_tolerated():
    a = _series("A", 100, drift=0.002)
    b = _series("B", 100, drift=0.006)
    gap = {b[70]["date"], b[71]["date"]}
    res = run_rotation({"A": a, "B": _drop(b, gap)}, CFG, 1000.0)
    assert res.end_value > 0
