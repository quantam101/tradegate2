"""Walk-forward parameter search.

Pure-stdlib TPE-style sampler: warm up with random draws, then bias
subsequent trials around the top-quantile observations (kernel-density
style refinement). This replaces the spec's Optuna-synthetic-curve
placeholder — the objective here is the real replay backtester.
"""

from __future__ import annotations

import random
from collections.abc import Callable

# name -> (low, high, step)
SEARCH_SPACE: dict[str, tuple[float, float, float]] = {
    "atr_multiplier": (1.5, 4.0, 0.1),      # wider stops ride trends longer
    "safety_factor": (0.15, 0.60, 0.05),
    "mom_window": (10, 40, 5),              # trend lookback bars
    "rsi_overbought": (60, 85, 5),          # alpha entry ceiling
    "rsi_oversold": (25, 40, 5),            # beta entry floor
    "max_trade_fraction": (0.04, 0.25, 0.01),
}


def _sample(space, rng, good_trials=None):
    if good_trials:
        base = rng.choice(good_trials)
        params = {}
        for name, (lo, hi, step) in space.items():
            center = base.get(name, (lo + hi) / 2)
            val = rng.gauss(center, (hi - lo) / 6)
            val = min(hi, max(lo, round(val / step) * step))
            params[name] = round(val, 4)
        return params
    return {n: round(rng.uniform(lo, hi) / step) * step
            for n, (lo, hi, step) in space.items()}


def tpe_search(objective: Callable[[dict], tuple[float, dict]],
               n_trials: int = 24, warmup: int = 8,
               seed: int = 42) -> tuple[float, dict, list[dict]]:
    """Returns (best_score, best_params, all_trials).

    ``objective(params) -> (score, report)``; report rides along for
    telemetry/audit.
    """
    rng = random.Random(seed)
    trials: list[dict] = []
    for i in range(n_trials):
        good = sorted((t for t in trials if t["score"] > float("-inf")),
                      key=lambda t: t["score"], reverse=True)[:max(1, len(trials) // 4)]
        params = _sample(SEARCH_SPACE, rng, [g["params"] for g in good] or None)
        score, report = objective(params)
        trials.append({"params": params, "score": score, "report": report})
    best = max(trials, key=lambda t: t["score"])
    return best["score"], best["params"], trials


def walk_forward_windows(ticks: list, n_windows: int = 3,
                         train_frac: float = 0.7) -> list[tuple]:
    """Split an ordered tick list into rolling (train, test) windows —
    out-of-sample evaluation, not curve-fitting on one period."""
    w = len(ticks) // (n_windows + 1)
    out = []
    for i in range(n_windows):
        seg = ticks[i * w:(i + 2) * w]
        cut = int(len(seg) * train_frac)
        out.append((seg[:cut], seg[cut:]))
    return out
