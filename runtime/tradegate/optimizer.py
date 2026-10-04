"""Walk-forward parameter search.

Pure-stdlib TPE-style sampler: warm up with random draws, then bias
subsequent trials around the top-quantile observations (kernel-density
style refinement). This replaces the spec's Optuna-synthetic-curve
placeholder — the objective here is the real replay backtester.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List, Tuple

# name -> (low, high, step)
SEARCH_SPACE: Dict[str, Tuple[float, float, float]] = {
    "min_imbalance": (1.6, 3.2, 0.1),
    "atr_multiplier": (1.2, 2.6, 0.1),
    "safety_factor": (0.15, 0.50, 0.05),
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


def tpe_search(objective: Callable[[dict], Tuple[float, dict]],
               n_trials: int = 24, warmup: int = 8,
               seed: int = 42) -> Tuple[float, dict, List[dict]]:
    """Returns (best_score, best_params, all_trials).

    ``objective(params) -> (score, report)``; report rides along for
    telemetry/audit.
    """
    rng = random.Random(seed)
    trials: List[dict] = []
    for i in range(n_trials):
        good = sorted((t for t in trials if t["score"] > float("-inf")),
                      key=lambda t: t["score"], reverse=True)[:max(1, len(trials) // 4)]
        params = _sample(SEARCH_SPACE, rng, [g["params"] for g in good] or None)
        score, report = objective(params)
        trials.append({"params": params, "score": score, "report": report})
    best = max(trials, key=lambda t: t["score"])
    return best["score"], best["params"], trials


def walk_forward_windows(ticks: list, n_windows: int = 3,
                         train_frac: float = 0.7) -> List[tuple]:
    """Split an ordered tick list into rolling (train, test) windows —
    out-of-sample evaluation, not curve-fitting on one period."""
    w = len(ticks) // (n_windows + 1)
    out = []
    for i in range(n_windows):
        seg = ticks[i * w:(i + 2) * w]
        cut = int(len(seg) * train_frac)
        out.append((seg[:cut], seg[cut:]))
    return out
