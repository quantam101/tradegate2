import json

from runtime.tradegate.dip_paper import run_dip_paper
from runtime.tradegate.dipbuy import DipConfig

CFG = DipConfig(universe=("A", "B"), trend_sma=20, exit_sma=5)
TODAY = "2025-02-05"  # day after the last bar (32 bars → 2025-02-04)


def _bars(closes):
    return [{"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]


DIP = _bars([100 + i for i in range(30)] + [126, 122])        # buy signal today
FLAT = _bars([50 + i * 0.1 for i in range(32)])                # no signal


class FakeRB:
    def __init__(self, positions, accept=True, orders=None):
        self._pos, self.sent, self.accept = positions, [], accept
        self.orders = orders or {}

    def equity(self):
        return 9000.0

    def positions(self):
        return dict(self._pos)

    def order(self, oid):
        return self.orders.get(oid)

    def submit(self, o):
        self.sent.append(o)
        return {"id": f"o{len(self.sent)}"} if self.accept else None


def test_buys_dip_with_equal_slot_and_tracks_ownership(tmp_path):
    data = {"A": DIP, "B": FLAT}
    rb = FakeRB({})
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, TODAY)
    assert rec["signals"] == {"A": "buy"}
    assert rb.sent[0].symbol == "A" and rb.sent[0].notional == 500  # 1000 / 2
    assert json.loads((tmp_path / "state.json").read_text())["owned"] == ["A"]


def test_never_sells_positions_it_does_not_own(tmp_path):
    up = _bars([100 + i for i in range(30)] + [120, 125, 131])  # would be a sell
    data = {"A": up, "B": FLAT}
    rb = FakeRB({"A": 700.0})  # held, but opened by someone else
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, "2025-02-06")
    assert "A" not in rec["signals"] or rec["signals"]["A"] != "sell"
    assert all(not o.close_all for o in rb.sent)


def test_sells_owned_position_when_bounce_completes(tmp_path):
    up = _bars([100 + i for i in range(30)] + [120, 125, 131])
    data = {"A": up, "B": FLAT}
    (tmp_path / "state.json").write_text(json.dumps({"owned": ["A"]}))
    rb = FakeRB({"A": 520.0})
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, "2025-02-06")
    assert rec["signals"]["A"] == "sell" and rb.sent[0].close_all
    st = json.loads((tmp_path / "state.json").read_text())
    # accepted ≠ filled: still owned, exit tracked until reconciled
    assert st["owned"] == ["A"] and st["open"]["A"]["side"] == "sell"


def test_rejected_buy_not_marked_owned(tmp_path):
    data = {"A": DIP, "B": FLAT}
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s],
                        FakeRB({}, accept=False), TODAY)
    assert rec["orders"][0]["accepted"] is False
    assert json.loads((tmp_path / "state.json").read_text())["owned"] == []


def test_stale_data_places_nothing(tmp_path):
    data = {"A": DIP, "B": FLAT}
    rb = FakeRB({})
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, "2025-03-30")
    assert "deferred_stale_data" in rec and rb.sent == []


def test_data_only_without_execute(tmp_path):
    data = {"A": DIP, "B": FLAT}
    rec = run_dip_paper(1000, False, CFG, tmp_path, lambda s: data[s], None, TODAY)
    assert rec["signals"] == {"A": "buy"} and not rec["executed"]


def _state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


def test_open_buy_blocks_duplicate_across_holiday(tmp_path):
    data = {"A": DIP, "B": FLAT}
    rb = FakeRB({})
    run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, TODAY)
    rb.orders = {"o1": {"status": "accepted", "filled_qty": "0"}}  # still queued
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, TODAY)
    assert len(rb.sent) == 1 and "A" not in rec["signals"]


def test_filled_sell_credits_slot_and_next_buy_uses_it(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "owned": ["A"], "slots": {"A": 500.0, "B": 500.0},
        "open": {"A": {"id": "s1", "side": "sell"}}}))
    rb = FakeRB({}, orders={"s1": {"status": "filled", "filled_qty": "4",
                                   "filled_avg_price": "105"}})
    data = {"A": DIP, "B": FLAT}  # fresh dip on A today
    run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, TODAY)
    st = _state(tmp_path)
    assert rb.sent[0].side == "buy" and rb.sent[0].notional == 420.0  # 4 × 105
    assert st["slots"]["A"] == 420.0


def test_cancelled_sell_keeps_ownership_and_retries(tmp_path):
    up = _bars([100 + i for i in range(30)] + [120, 125, 131])
    (tmp_path / "state.json").write_text(json.dumps({
        "owned": ["A"], "open": {"A": {"id": "s1", "side": "sell"}}}))
    rb = FakeRB({"A": 520.0}, orders={"s1": {"status": "canceled", "filled_qty": "0"}})
    data = {"A": up, "B": FLAT}
    rec = run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, "2025-02-06")
    assert rec["signals"]["A"] == "sell" and rb.sent[0].close_all
    assert _state(tmp_path)["owned"] == ["A"]


def test_cancelled_buy_releases_symbol_with_slot_intact(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "owned": ["A"], "slots": {"A": 500.0, "B": 500.0},
        "open": {"A": {"id": "b1", "side": "buy"}}}))
    rb = FakeRB({}, orders={"b1": {"status": "expired", "filled_qty": "0"}})
    data = {"A": FLAT, "B": FLAT}
    run_dip_paper(1000, True, CFG, tmp_path, lambda s: data[s], rb, TODAY)
    st = _state(tmp_path)
    assert st["owned"] == [] and st["open"] == {} and st["slots"]["A"] == 500.0
