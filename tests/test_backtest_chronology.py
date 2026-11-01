"""Replay must reject time travel before starting any agent or broker."""

from unittest.mock import AsyncMock

import pytest

from runtime.tradegate import backtest
from runtime.tradegate.events import Tick


def tick(symbol, timestamp):
    return Tick(symbol, timestamp, 100, 99, 101, 1, 1, 0)


@pytest.mark.parametrize("ticks", [
    [tick("A", 2), tick("A", 1)],
    [tick("A", 2), tick("B", 1)],
    [tick("A", float("nan"))],
    [tick("A", float("inf"))],
    [tick("A", float("-inf"))],
])
def test_invalid_timeline_rejected_before_pipeline(ticks, monkeypatch):
    pipeline = AsyncMock()
    monkeypatch.setattr(backtest, "_run_pipeline", pipeline)
    with pytest.raises(ValueError, match="timestamp"):
        backtest.run_backtest(iter(ticks))
    pipeline.assert_not_called()


def test_equal_timestamps_and_ordered_generator_are_preserved(monkeypatch):
    ticks = [tick("A", 1), tick("B", 1), tick("A", 2)]
    pipeline = AsyncMock(return_value=type("Broker", (), {"fills": []})())
    monkeypatch.setattr(backtest, "_run_pipeline", pipeline)
    assert backtest.run_backtest(iter(ticks))["trades"] == 0
    assert pipeline.call_args.args[0] == ticks


def test_empty_replay_remains_valid():
    assert backtest.run_backtest(iter(()))["trades"] == 0
