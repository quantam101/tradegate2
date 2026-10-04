"""Engine configuration with atomic, versioned hot-swapping.

The original spec mutated one shared ``EngineConfig`` from Agent 9 while
Agents 2–7 read it mid-flight — a data race that also breaks the "zero
shared mutable state" pillar. Here ``ConfigStore`` keeps an immutable
snapshot; readers call ``snapshot()`` (O(1), no lock needed for reads
under asyncio) and Agent 9 calls ``swap()`` to publish a new version.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class EngineConfig:
    """Immutable parameter manifest. Bump via ConfigStore.swap()."""

    min_imbalance: float = 2.2          # Agent 2/3: bid/ask depth trigger
    cvd_min: float = 0.0                # Agent 3: required CVD sign for sweeps
    atr_multiplier: float = 1.8         # Agent 6/7: stop distance = mult * ATR
    atr_window: int = 14                # bars used for ATR estimation
    safety_factor: float = 0.33         # fractional Kelly scale
    max_drawdown_limit: float = 0.04    # equity circuit breaker (fraction)
    max_trade_fraction: float = 0.04    # hard per-trade capital ceiling
    min_win_rate: float = 0.60          # WFO acceptance floor
    rolling_win_rate: float = 0.60      # updated from live ledger stats
    rolling_payout_ratio: float = 1.2   # avg win / avg loss from ledger
    cancel_after_sec: float = 30.0      # resting-order expiry (paper: queue TTL)
    version: int = 1
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class ConfigStore:
    """Publishes immutable EngineConfig snapshots.

    ``snapshot()`` returns the current manifest. ``swap()`` validates,
    versions, persists (if manifest_path set) and atomically replaces it.
    """

    def __init__(self, config: Optional[EngineConfig] = None,
                 manifest_path: Optional[Path] = None):
        self._config = config or EngineConfig()
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self._listeners = []

    def snapshot(self) -> EngineConfig:
        return self._config

    def on_swap(self, callback) -> None:
        self._listeners.append(callback)

    def swap(self, **changes) -> EngineConfig:
        data = self._config.to_dict()
        data.update(changes)
        data["version"] = self._config.version + 1
        data["last_updated"] = time.time()
        new = EngineConfig(**data)
        self._config = new
        if self.manifest_path:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.manifest_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(new.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(self.manifest_path)
        for cb in self._listeners:
            cb(new)
        return new

    @classmethod
    def from_manifest(cls, path: Path) -> "ConfigStore":
        p = Path(path)
        if p.exists():
            return cls(EngineConfig(**json.loads(p.read_text())), manifest_path=p)
        return cls(manifest_path=p)
