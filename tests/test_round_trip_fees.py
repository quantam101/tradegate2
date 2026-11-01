"""Regression: entry fees must count against the round trip they belong to.

PaperBroker books the entry fee on the ENTRY fill (pnl=-fee) and the exit
fee inside the EXIT fill. Win/loss classification and backtest P&L used to
look only at EXIT fills, so a round trip whose small gross gain was eaten by
the entry fee was scored as a win — inflating win_rate (the WFO acceptance
gate), avg_win/avg_loss (Kelly inputs), net_pnl, ROI and drawdown.
"""

import asyncio

import pytest

from runtime.tradegate.backtest import compute_metrics
from runtime.tradegate.broker import Fill, Order, PaperBroker
from runtime.tradegate.events import Side, Strategy, Tick


def _fee_eaten_round_trip() -> PaperBroker:
    # 100 bps fee each side on $1,000. Entry at 100, EOD exit at 101.5:
    # gross +$15.00, exit fee ~$10.15 -> exit leg ~ +$4.85;
    # entry fee $10.00 -> round trip ~ -$5.15 (a loss).
    broker = PaperBroker(fee_bps=100.0)
    order = Order(symbol="SPY", side=Side.BUY, strategy=list(Strategy)[0],
                  capital=1000.0, stop_price=95.0, take_profit=100.5,
                  placed_ts=0.0, expires_ts=30.0)
    asyncio.run(broker.submit(order, ref_price=100.0))
    asyncio.run(broker.close_all(ref_price=101.5, ts=60.0,
                                 ref_symbol="SPY"))
    return broker


def test_entry_fee_turns_marginal_exit_into_a_loss_in_broker_stats():
    broker = _fee_eaten_round_trip()
    exit_fill = [f for f in broker.fills if f.kind.startswith("EXIT")][0]
    assert exit_fill.pnl > 0, "precondition: exit leg alone looks profitable"
    stats = broker.stats()
    assert stats["net_pnl"] < 0
    assert stats["trades"] == 1
    assert stats["win_rate"] == 0.0
    assert stats["avg_win"] == 0.0
    assert stats["avg_loss"] == pytest.approx(-stats["net_pnl"])


def test_backtest_metrics_charge_entry_fees():
    broker = _fee_eaten_round_trip()
    m = compute_metrics(1000.0, broker.fills)
    total = sum(f.pnl for f in broker.fills)
    assert m["win_rate"] == 0.0
    assert m["net_pnl"] == pytest.approx(total)
    assert m["roi"] == pytest.approx(total / 1000.0)
    assert m["max_drawdown"] > 0


def test_open_position_entry_fee_still_counts_in_net_pnl():
    fills = [
        Fill("a", "SPY", Side.BUY, 1, 100, 0, "ENTRY", pnl=-1.0),
        Fill("a", "SPY", Side.BUY, 1, 110, 1, "EXIT_TP", pnl=9.0),
        Fill("b", "QQQ", Side.BUY, 1, 100, 2, "ENTRY", pnl=-1.0),  # still open
    ]
    m = compute_metrics(1000.0, fills)
    assert m["trades"] == 1
    assert m["win_rate"] == 1.0
    assert m["avg_win"] == pytest.approx(8.0)
    assert m["net_pnl"] == pytest.approx(7.0)
