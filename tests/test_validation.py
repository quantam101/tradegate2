import random

import pytest

from runtime.tradegate.validation import deflated_sharpe, expected_max_sharpe, pbo


def _noise(n, mu, sd, seed):
    r = random.Random(seed)
    return [r.gauss(mu, sd) for _ in range(n)]


def test_pbo_high_when_all_configs_are_noise():
    cfgs = {f"c{i}": _noise(400, 0.0, 0.01, i) for i in range(12)}
    assert pbo(cfgs, n_blocks=8)["pbo"] > 0.3


def test_pbo_low_when_one_config_has_real_edge():
    cfgs = {f"c{i}": _noise(400, 0.0, 0.01, i) for i in range(11)}
    cfgs["edge"] = _noise(400, 0.004, 0.01, 99)
    assert pbo(cfgs, n_blocks=8)["pbo"] < 0.1


def test_pbo_validates_inputs():
    with pytest.raises(ValueError):
        pbo({"a": [0.0] * 10, "b": [0.0] * 9})
    with pytest.raises(ValueError):
        pbo({"a": [0.0] * 40, "b": [0.0] * 40}, n_blocks=3)


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0


def test_deflated_sharpe_penalises_many_trials():
    rets = _noise(500, 0.001, 0.01, 7)
    few = deflated_sharpe(rets, 2, [0.0, 0.1])["dsr"]
    many = deflated_sharpe(rets, 1000, [x / 100 for x in range(-10, 11)])["dsr"]
    assert many < few
    assert 0 <= many <= 1 and 0 <= few <= 1
