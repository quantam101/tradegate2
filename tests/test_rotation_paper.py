import json

import pytest

from runtime.tradegate.rotation import RotationConfig
from runtime.tradegate.rotation_paper import (
    is_rebalance_day,
    plan_rebalance,
    run_rotation_paper,
)


def test_plan_sells_first_and_closes_dropped_positions():
    orders = plan_rebalance(1000, {"OLD": 300.0, "KEEP": 200.0},
                            {"KEEP": 0.5, "NEW": 0.5})
    assert orders[0].side == "sell" and orders[0].symbol == "OLD"
    assert orders[0].close_all
    by = {o.symbol: o for o in orders}
    assert by["KEEP"].side == "buy" and by["KEEP"].notional == pytest.approx(300)
    assert by["NEW"].notional == pytest.approx(500)


def test_plan_skips_small_drift():
    assert plan_rebalance(1000, {"A": 495.0}, {"A": 0.5}) == []


def test_rebalance_cadence():
    dates = [f"2026-01-{d:02d}" for d in range(1, 31)]
    assert is_rebalance_day(dates, None, 21)
    assert not is_rebalance_day(dates, "2026-01-20", 21)
    assert is_rebalance_day(dates, "2026-01-05", 21)


def _bars(n, drift):
    px, out = 100.0, []
    for i in range(n):
        px *= 1 + drift
        out.append({"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
                    "open": px, "high": px, "low": px, "close": px})
    return out


CFG = RotationConfig(lookback=20, top_k=2, sma=10, vol_window=10, rebalance_every=5)


class FakeRebalancer:
    def __init__(self, positions):
        self._pos, self.sent = positions, []

    def equity(self):
        return 5000.0

    def positions(self):
        return dict(self._pos)

    def submit(self, o):
        self.sent.append(o)
        return {"id": "x"}


def test_paper_run_logs_target_and_respects_capital_cap(tmp_path):
    data = {"UP": _bars(60, 0.01), "DOWN": _bars(60, -0.01)}
    rb = FakeRebalancer({})
    rec = run_rotation_paper(capital=1000, execute=True, universe=list(data), cfg=CFG,
                             out_dir=tmp_path, bars_fn=lambda s: data[s], rebalancer=rb)
    assert rec["rebalance_day"] and rec["executed"]
    assert set(rec["target_weights"]) == {"UP"}
    assert rec["budget"] == 1000  # capped below the 5000 account equity
    assert sum(o.notional for o in rb.sent) == pytest.approx(1000)
    assert json.loads((tmp_path / "state.json").read_text())["last_rebalance"]


def test_paper_run_defers_when_holding_has_no_fresh_bar(tmp_path):
    data = {"UP": _bars(60, 0.01), "STALE": _bars(59, 0.01)}
    rb = FakeRebalancer({"STALE": 400.0})
    rec = run_rotation_paper(capital=1000, execute=True, universe=list(data), cfg=CFG,
                             out_dir=tmp_path, bars_fn=lambda s: data[s], rebalancer=rb)
    assert rec["deferred_unpriced_holdings"] == ["STALE"]
    assert rb.sent == [] and not rec["executed"]
    assert not (tmp_path / "state.json").exists()


def test_paper_run_without_execute_places_nothing(tmp_path):
    data = {"UP": _bars(60, 0.01)}
    rec = run_rotation_paper(capital=1000, execute=False, universe=list(data), cfg=CFG,
                             out_dir=tmp_path, bars_fn=lambda s: data[s])
    assert not rec["executed"] and "orders" not in rec
