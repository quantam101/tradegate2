import json

import pytest

from runtime.tradegate import truth_ledger as tl


def _series(sym, n, start=100.0, drift=0.001, start_day=0):
    bars, px = [], start
    for i in range(n):
        px *= 1 + drift
        d = f"2025-{1 + (start_day + i) // 28:02d}-{1 + (start_day + i) % 28:02d}"
        bars.append({"date": d, "open": px, "high": px * 1.01,
                     "low": px * 0.99, "close": px})
    return bars


def _bars_fn(hist):
    def fn(symbol):
        if symbol not in hist:
            raise ValueError(f"no bars for {symbol}")
        return hist[symbol]
    return fn


@pytest.fixture()
def hist():
    return {s: _series(s, 250, drift=0.002)
            for s in ["SPY", "QQQ", "IWM", "GLD", "TLT", "IBIT", "ETHA",
                      "FXE", "FXY", "UUP"]}


def test_no_credentials_records_model_only(hist, tmp_path, monkeypatch):
    for k in ("ALPACA_PAPER_KEY", "ALPACA_PAPER_SECRET",
              "ALPACA_DIP_PAPER_KEY", "ALPACA_DIP_PAPER_SECRET"):
        monkeypatch.delenv(k, raising=False)
    records = tl.run_truth_ledger(out_dir=tmp_path, bars_fn=_bars_fn(hist),
                                  today="2026-01-05")
    assert len(records) == 2
    for r in records:
        assert r["broker_status"] == "no_credentials"
        assert r["broker_equity"] is None and r["diff_pct"] is None
        assert r["model_equity"] is not None
    lines = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert {"date", "strategy", "model_equity", "broker_equity",
                "diff_pct", "positions_match", "broker_status"} <= set(rec)


def test_broker_fetch_error_is_degraded_not_fatal(hist, tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "s")
    monkeypatch.delenv("ALPACA_DIP_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_DIP_PAPER_SECRET", raising=False)

    def boom(key, secret):
        raise OSError("alpaca unreachable")

    monkeypatch.setattr(tl, "broker_snapshot", boom)
    records = tl.run_truth_ledger(out_dir=tmp_path, bars_fn=_bars_fn(hist),
                                  today="2026-01-05")
    rot = next(r for r in records if r["strategy"] == "rotation")
    assert rot["broker_status"] == "fetch_error"
    assert rot["model_equity"] is not None and rot["broker_equity"] is None
    assert any("broker fetch failed" in n for n in rot["notes"])


def test_positions_match_and_diff(hist, tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "s")

    def fake(key, secret):
        return {"equity": 1100.0, "cash": 0.0, "positions": {}}

    monkeypatch.setattr(tl, "broker_snapshot", fake)
    records = tl.run_truth_ledger(out_dir=tmp_path, bars_fn=_bars_fn(hist),
                                  today="2026-01-05")
    rot = next(r for r in records if r["strategy"] == "rotation")
    assert rot["broker_status"] == "ok"
    assert rot["broker_equity"] == 1100.0
    assert rot["diff_pct"] == pytest.approx(
        (1100.0 - rot["model_equity"]) / rot["model_equity"] * 100, abs=1e-3)
    assert isinstance(rot["positions_match"], bool)


def test_all_data_failing_records_no_market_data(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_DIP_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_DIP_PAPER_SECRET", raising=False)

    def fn(symbol):
        raise OSError("network down")

    records = tl.run_truth_ledger(out_dir=tmp_path, bars_fn=fn,
                                  today="2026-01-05")
    assert all(r["broker_status"] == "no_market_data" for r in records)
    assert all(r["model_equity"] is None for r in records)
