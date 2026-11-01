"""Known-answer checks against the actual paper broker ledger."""
import asyncio

import pytest

from runtime.tradegate.backtest import compute_metrics
from runtime.tradegate.broker import Order, PaperBroker
from runtime.tradegate.events import Side, Strategy


@pytest.mark.parametrize('slippage', [0, 50])
def test_round_trip_includes_both_fees_and_adverse_slippage(slippage):
    broker = PaperBroker(fee_bps=10, slippage_bps=slippage)
    async def trade():
        await broker.submit(Order('X', Side.BUY, Strategy.BETA_REVERSION,
                                  100, 80, 120, 0, 30), 100)
        await broker.close_all(100, 1)
    asyncio.run(trade())
    metrics = compute_metrics(1000, broker.fills)
    entry_price = 100 * (1 + slippage / 10000)
    exit_price = 100 * (1 - slippage / 10000)
    proceeds = 100 / entry_price * exit_price
    expected = proceeds - 100 - 0.1 - proceeds * 0.001
    assert metrics['net_pnl'] == pytest.approx(expected)
    assert metrics['net_pnl'] == pytest.approx(broker.stats()['net_pnl'])
    assert metrics['roi'] == pytest.approx(expected / 1000)
    assert metrics['avg_loss'] == pytest.approx(-expected)
    assert metrics['max_drawdown'] == pytest.approx(-expected / 1000)


def test_entry_fee_changes_small_exit_gain_into_round_trip_loss():
    broker = PaperBroker(fee_bps=10)
    async def trade():
        await broker.submit(Order('X', Side.BUY, Strategy.BETA_REVERSION,
                                  100, 80, 120, 0, 30), 100)
        await broker.close_all(100.15, 1)
    asyncio.run(trade())
    metrics = compute_metrics(1000, broker.fills)
    assert metrics['net_pnl'] == pytest.approx(-0.05015)
    assert metrics['win_rate'] == 0
    assert metrics['profit_factor'] == 0


def test_open_position_entry_fee_is_not_erased():
    broker = PaperBroker(fee_bps=10)
    asyncio.run(broker.submit(Order('X', Side.BUY, Strategy.BETA_REVERSION,
                                   100, 80, 120, 0, 30), 100))
    metrics = compute_metrics(1000, broker.fills)
    assert metrics['trades'] == 0
    assert metrics['net_pnl'] == pytest.approx(-0.1)
    assert metrics['max_drawdown'] == pytest.approx(0.0001)
