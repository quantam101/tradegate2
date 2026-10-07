"""TradeGate ProfitEngine — stateful micro-agent mesh (paper trading).

Nine single-purpose asyncio agents connected by non-blocking queues:

    feed -> ingest -> depth/CVD -> regime -> {alpha, beta}
         -> risk (fractional Kelly + drawdown breaker)
         -> execution (paper broker) -> telemetry -> WFO optimizer

Everything is stdlib-only and runs without exchange credentials. Live
trading is intentionally absent: ``Broker`` is an interface, and the only
implementation shipped here is ``PaperBroker``.
"""

from .config import ConfigStore, EngineConfig
from .events import MarketEvent, Signal, Tick
from .orchestrator import TradeGateOrchestrator

__all__ = [
    "ConfigStore",
    "EngineConfig",
    "MarketEvent",
    "Signal",
    "Tick",
    "TradeGateOrchestrator",
]
