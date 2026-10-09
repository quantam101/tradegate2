"""Overfitting defences for strategy selection.

Trying many parameter sets and keeping the best one inflates backtest
results. Two standard corrections:

* **Probability of Backtest Overfitting (PBO)** — Bailey, Borwein,
  López de Prado & Zhu (2015), via Combinatorially Symmetric
  Cross-Validation (CSCV). Split the return history into S blocks; for every
  way of choosing S/2 blocks as in-sample, find the best config in-sample
  and see where it ranks out-of-sample. PBO is the share of splits where
  the in-sample winner lands in the bottom half out-of-sample. Lower is
  better; above 0.5 means selection is worse than a coin flip.

* **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado (2014). The
  probability that the observed Sharpe exceeds the best Sharpe you'd expect
  from ``n_trials`` skill-less strategies, adjusted for sample length,
  skew and fat tails. Above 0.95 is the usual bar.

Pure standard library — no numpy dependency.
"""

from __future__ import annotations

import itertools
import math
import statistics
from statistics import NormalDist

_N = NormalDist()
_EULER = 0.5772156649015329


def _sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    sd = statistics.pstdev(rets)
    return statistics.mean(rets) / sd if sd > 0 else 0.0


def pbo(returns: dict[str, list[float]], n_blocks: int = 10) -> dict:
    """CSCV probability of backtest overfitting.

    ``returns`` maps config name → per-period returns, all the same length
    and aligned in time. Returns ``{"pbo", "n_splits", "logits"}``.
    """
    names = list(returns)
    if len(names) < 2:
        raise ValueError("need at least two configs")
    length = len(returns[names[0]])
    if any(len(r) != length for r in returns.values()):
        raise ValueError("all return series must be the same length")
    if n_blocks % 2 or n_blocks < 2:
        raise ValueError("n_blocks must be even and >= 2")
    size = length // n_blocks
    if size < 2:
        raise ValueError("not enough observations for that many blocks")
    blocks = [range(i * size, (i + 1) * size) for i in range(n_blocks)]
    logits = []
    for ins in itertools.combinations(range(n_blocks), n_blocks // 2):
        oos = [b for b in range(n_blocks) if b not in ins]
        idx_in = [i for b in ins for i in blocks[b]]
        idx_out = [i for b in oos for i in blocks[b]]
        sr_in = {n: _sharpe([returns[n][i] for i in idx_in]) for n in names}
        sr_out = {n: _sharpe([returns[n][i] for i in idx_out]) for n in names}
        best = max(names, key=lambda n: sr_in[n])
        # relative OOS rank of the IS winner, in (0, 1)
        rank = sorted(names, key=lambda n: sr_out[n]).index(best) + 1
        w = rank / (len(names) + 1)
        logits.append(math.log(w / (1 - w)))
    return {"pbo": sum(1 for x in logits if x <= 0) / len(logits),
            "n_splits": len(logits), "logits": logits}


def expected_max_sharpe(n_trials: int, sharpe_var: float) -> float:
    """Expected maximum per-period Sharpe among ``n_trials`` skill-less
    strategies whose Sharpes have variance ``sharpe_var``."""
    if n_trials < 2 or sharpe_var <= 0:
        return 0.0
    return math.sqrt(sharpe_var) * (
        (1 - _EULER) * _N.inv_cdf(1 - 1 / n_trials)
        + _EULER * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(rets: list[float], n_trials: int,
                    trial_sharpes: list[float]) -> dict:
    """Deflated Sharpe ratio for the chosen strategy's per-period returns.

    ``trial_sharpes`` are the per-period Sharpes of every config tried
    (their spread sets the bar). Returns ``{"dsr", "sharpe", "sr0"}`` with
    per-period Sharpes; multiply by sqrt(252) to annualize daily figures.
    """
    t = len(rets)
    if t < 3:
        raise ValueError("need at least three observations")
    sr = _sharpe(rets)
    var = statistics.pvariance(trial_sharpes) if len(trial_sharpes) > 1 else 0.0
    sr0 = expected_max_sharpe(n_trials, var)
    m = statistics.mean(rets)
    sd = statistics.pstdev(rets)
    if sd == 0:
        return {"dsr": 0.0, "sharpe": 0.0, "sr0": sr0}
    skew = sum((r - m) ** 3 for r in rets) / t / sd ** 3
    kurt = sum((r - m) ** 4 for r in rets) / t / sd ** 4
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - sr0) * math.sqrt(t - 1) / denom
    return {"dsr": _N.cdf(z), "sharpe": sr, "sr0": sr0}
