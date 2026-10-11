import pytest

from runtime.tradegate.dipbuy import DipConfig, rsi, run_dipbuy, signal

CFG = DipConfig(universe=("A",), trend_sma=20, exit_sma=5, cost_bps=0.0)


def _bars(closes):
    return [{"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]


def test_rsi_extremes():
    assert rsi([1, 2, 3], 2) == 100.0
    assert rsi([3, 2, 1], 2) == 0.0
    assert rsi([1, 2], 2) is None


def test_buys_sharp_dip_in_uptrend_only():
    up = [100 + i for i in range(30)]
    dip = up + [up[-1] - 3, up[-1] - 6]
    assert signal(dip, holding=False, cfg=CFG) == "buy"
    down = [130 - i for i in range(32)]
    assert signal(down, holding=False, cfg=CFG) is None  # below trend: no dip buy


def test_sells_when_back_above_short_average():
    closes = [100 + i for i in range(30)] + [120, 125, 131]
    assert signal(closes, holding=True, cfg=CFG) == "sell"


def test_round_trip_fills_next_open_and_profits_from_bounce():
    closes = [100 + i for i in range(30)] + [126, 122, 124, 128, 133, 134]
    res = run_dipbuy({"A": _bars(closes)}, CFG, 1000.0)
    buys = [t for t in res.trades if t["side"] == "BUY"]
    sells = [t for t in res.trades if t["side"] == "SELL"]
    assert buys and sells
    d = [b["date"] for b in _bars(closes)]
    # dip confirmed at close of index 31 → bought at index 32's open
    assert buys[0]["date"] == d[32] and buys[0]["price"] == closes[32]
    assert sells[0]["pnl"] > 0


def test_costs_reduce_result_and_slots_are_equal():
    closes = [100 + i for i in range(30)] + [126, 122, 124, 128, 133, 134]
    data = {"A": _bars(closes), "B": _bars([50 + i * 0.1 for i in range(36)])}
    two = DipConfig(universe=("A", "B"), trend_sma=20, exit_sma=5, cost_bps=0.0)
    free = run_dipbuy(data, two, 1000.0)
    paid = run_dipbuy(data, DipConfig(**{**two.to_dict(), "universe": ("A", "B"),
                                         "cost_bps": 50.0}), 1000.0)
    assert paid.end_value < free.end_value
    buy = next(t for t in free.trades if t["side"] == "BUY")
    assert buy["qty"] * buy["price"] == pytest.approx(500.0)  # half the capital


def test_start_window_and_missing_universe():
    closes = [100 + i for i in range(40)]
    res = run_dipbuy({"A": _bars(closes)}, CFG, 1000.0, start=_bars(closes)[30]["date"])
    assert res.equity[0][0] == _bars(closes)[30]["date"]
    with pytest.raises(ValueError):
        run_dipbuy({"Z": _bars(closes)}, CFG, 1000.0)
