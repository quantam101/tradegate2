from runtime.tradegate import cost_check as cc


def _series(sym, n, start=100.0, drift=0.001, start_day=0):
    bars, px = [], start
    for i in range(n):
        px *= 1 + drift
        d = f"2025-{1 + (start_day + i) // 28:02d}-{1 + (start_day + i) % 28:02d}"
        bars.append({"date": d, "open": px, "high": px * 1.01,
                     "low": px * 0.99, "close": px})
    return bars


def _bars_fn(hist):
    def fn(symbol, range_="2y"):
        if symbol not in hist:
            raise ValueError(f"no bars for {symbol}")
        return hist[symbol]
    return fn


def test_report_shape_and_monotonic_cost_impact():
    hist = {s: _series(s, 250, drift=0.002)
            for s in ["SPY", "QQQ", "IWM", "GLD", "TLT", "IBIT", "ETHA",
                      "FXE", "FXY", "UUP"]}
    report = cc.run_cost_check(costs=(0.0, 10.0, 20.0), bars_fn=_bars_fn(hist))
    assert "rotation" in report["strategies"]
    assert "dipbuy" in report["strategies"]
    assert "survives_at_max_cost" in report
    for strat in report["strategies"].values():
        rows = strat["by_cost_bps"]
        assert set(rows) == {"0", "10", "20"}
        for m in rows.values():
            assert {"roi", "sharpe", "max_drawdown", "win_rate",
                    "edge_survives"} <= set(m)
        # charging more can never help: end_value is non-increasing in cost
        assert (rows["0"]["end_value"] >= rows["10"]["end_value"]
                >= rows["20"]["end_value"])


def test_all_data_failing_raises():
    def fn(symbol, range_="2y"):
        raise OSError("network down")

    try:
        cc.run_cost_check(bars_fn=fn)
    except RuntimeError as e:
        assert "no market data" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
