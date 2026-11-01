"""The CLI must never tune candidates on the reported holdout frames."""
import json

from runtime.tradegate import __main__ as cli
from runtime.tradegate.events import Tick


def test_optimizer_selects_on_train_then_evaluates_holdout_once(monkeypatch, tmp_path, capsys):
    ticks = [Tick('X', i, 100, 99, 101, 1, 1, 0) for i in range(40)]
    windows = cli.walk_forward_windows(ticks)
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, '_ticks', lambda argv: ticks)
    monkeypatch.setattr(cli, 'run_backtest', lambda frames, cfg: calls.append(frames) or {'value': 1})
    monkeypatch.setattr(cli, 'score', lambda metrics, cfg, min_trades: 1)
    def search(objective, n_trials):
        objective({})
        objective({})
        return 1, {}, [{}, {}]
    monkeypatch.setattr(cli, 'tpe_search', search)
    cli.main(['optimize'])
    assert calls == [frames for train, test in windows for frames in (train, train, test)]
    report = json.loads(capsys.readouterr().out)
    assert len(report['heldout_reports']) == 3
    assert report['trials'] == 6
