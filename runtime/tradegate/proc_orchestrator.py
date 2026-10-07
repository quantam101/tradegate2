"""Process-per-agent mesh: each micro-agent runs in its own OS process.

Same pipeline as the asyncio orchestrator — Ingest → Depth → Sentiment →
Regime → (Alpha | Beta) → Risk → Exec → Telemetry — but every stage is a
separate ``multiprocessing.Process`` linked by ``mp.Queue``s, with a thin
async adapter so the agent code doesn't change at all.

Honest trade-offs (documented, not hidden):
- Isolation wins: one agent crashing or blocking can't stall the ring —
  the parent sees the dead process and flushes the pipeline.
- Cost: every event is pickled across a queue (~µs–ms per hop), so this
  mode is for resilience and CPU isolation, not lower latency. For daily
  paper cadence it costs nothing measurable; for sub-ms claims, it would
  be fiction either way.
- No optimizer in this mode (Agent 9 hot-swaps config in-memory — shared
  state across processes would need a real consensus layer; out of scope
  and out of honesty for a paper system).

Run:  python -m runtime.tradegate procpaper --steps 5000
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import time
from pathlib import Path

from .config import EngineConfig
from .events import MarketEvent

log = logging.getLogger("tradegate")


class _AsyncMPQueue:
    """asyncio-facing adapter over a multiprocessing.Queue.

    ``get`` runs the blocking call on a thread so the agent's event loop
    stays unblocked; ``put`` is async-symmetric. ``task_done``/``join``
    are no-ops — shutdown is coordinated by sentinel, not queue joins.
    """

    def __init__(self, mpq: mp.Queue):
        self._mpq = mpq

    async def get(self):
        return await asyncio.to_thread(self._mpq.get)

    async def put(self, item) -> None:
        await asyncio.to_thread(self._mpq.put, item)

    def task_done(self) -> None:  # mp.Queue has no join tracking
        return None

    async def join(self) -> None:
        return None


class _StaticStore:
    """Pickle-safe stand-in for ConfigStore in child processes (no hot-swap —
    Agent 9 doesn't run in this mode; config is fixed at spawn)."""

    def __init__(self, cfg_dict: dict):
        self._cfg = EngineConfig(**{k: v for k, v in cfg_dict.items()
                                    if k in EngineConfig.__dataclass_fields__})

    def snapshot(self) -> EngineConfig:
        return self._cfg


def _child(agent_factory, name_map: dict, queues: dict, cfg_dict: dict,
           shared: dict) -> None:
    """Child process entry: build the agent over async-adapted mp queues
    and run it until its sentinel arrives."""
    def q(local_name):
        real = name_map[local_name]
        return _AsyncMPQueue(queues[real]) if real else None

    store = _StaticStore(cfg_dict)
    agent = agent_factory(q, store, shared)
    asyncio.run(agent.run())


INITIAL_EQUITY = 1000.0


def _f_depth(q, store, _s):
    from .agents import DepthCvdAgent
    return DepthCvdAgent(q("in"), q("out"), store)


def _f_sentiment(q, store, _s):
    from .agents import SentimentAgent
    return SentimentAgent(q("in"), q("out"))


def _f_regime(q, store, _s):
    from .agents import RegimeAgent
    return RegimeAgent(q("in"), q("alpha"), q("beta"), q("drop"), store)


def _f_alpha(q, store, _s):
    from .agents import AlphaStrategyAgent
    return AlphaStrategyAgent(q("in"), q("out"), store)


def _f_beta(q, store, _s):
    from .agents import BetaStrategyAgent
    return BetaStrategyAgent(q("in"), q("out"), store)


def _f_risk(q, store, shared):
    from .agents import RiskAgent
    # realized equity shared from the exec process — the drawdown breaker
    # trips on real losses, not a constant
    return RiskAgent(q("in"), q("out"), store,
                     equity_ref=lambda: shared["equity"].value)


def _f_exec(q, store, shared):
    from .agents import ExecutionAgent
    from .broker import PaperBroker
    broker = PaperBroker(ledger_path=Path("data/tradegate/proc_fills.jsonl"))
    broker.equity_ref = lambda: shared["equity"].value
    broker.drawdown_limit_ref = (
        lambda: store.snapshot().max_drawdown_limit)

    def _probe(pnl: float) -> None:
        shared["equity"].value = INITIAL_EQUITY + pnl

    return ExecutionAgent(q("in"), q("out"), broker, store,
                          drive_exits=True, equity_probe=_probe)


def _f_telemetry(q, store, _s):
    from .agents import TelemetryAgent
    return TelemetryAgent(q("in"))


_STAGES = {
    "depth": _f_depth,
    "sentiment": _f_sentiment,
    "regime": _f_regime,
    "alpha": _f_alpha,
    "beta": _f_beta,
    "risk": _f_risk,
    "exec": _f_exec,
    "telemetry": _f_telemetry,
}

# queue name → (producer stage, consumer stage). "feed" is written by the
# parent ingest loop.
_LINKS = [
    ("feed", "depth"), ("depth_out", "sentiment"), ("senti_out", "regime"),
    ("regime_alpha", "alpha"), ("regime_beta", "beta"), ("regime_drop", None),
    ("alpha_out", "risk"), ("beta_out", "risk"), ("risk_out", "exec"),
    ("exec_out", "telemetry"),
]


async def run_procs(symbol: str = "PAPER/USD", steps: int = 5000,
                    config: EngineConfig | None = None,
                    ledger_path: Path | None = None) -> dict:
    """Spawn one OS process per agent stage; parent runs ingest + the
    dead-letter drain. Returns process liveness stats."""
    ctx = mp.get_context("spawn")
    queues = {name: ctx.Queue() for name, _ in _LINKS}
    cfg_dict = (config or EngineConfig()).to_dict()

    # Each stage's local port name → shared queue name, per the link table.
    out_names = {
        "depth": {"in": "feed", "out": "depth_out"},
        "sentiment": {"in": "depth_out", "out": "senti_out"},
        "regime": {"in": "senti_out", "alpha": "regime_alpha",
                   "beta": "regime_beta", "drop": "regime_drop"},
        "alpha": {"in": "regime_alpha", "out": "alpha_out"},
        "beta": {"in": "regime_beta", "out": "beta_out"},
        "risk": {"in": ["alpha_out", "beta_out"], "out": "risk_out"},
        "exec": {"in": "risk_out", "out": "exec_out"},
        "telemetry": {"in": "exec_out"},
    }

    # risk consumes BOTH alpha and beta outputs — fan-in: one shared queue.
    queues["signals"] = ctx.Queue()
    out_names["alpha"]["out"] = "signals"
    out_names["beta"]["out"] = "signals"
    out_names["risk"]["in"] = "signals"

    shared = {"equity": ctx.Value("d", INITIAL_EQUITY)}
    procs = []
    for name, factory in _STAGES.items():
        p = ctx.Process(
            target=_child, name=f"tg-{name}",
            args=(factory, out_names[name], queues, cfg_dict, shared),
            daemon=True)
        p.start()
        procs.append(p)

    from .feed import SyntheticFeed
    feed = SyntheticFeed(symbol=symbol, steps=steps)
    feed_q = queues["feed"]
    drop_q = queues["regime_drop"]

    # Dead-letter drain in a daemon thread — mp.Queue.empty()/get_nowait are
    # unreliable across processes, so this just blocks on get() forever.
    import threading
    stop_drain = threading.Event()

    def _drain():
        import queue as _queue_mod
        while not stop_drain.is_set():
            try:
                drop_q.get(timeout=0.2)
            except (_queue_mod.Empty, EOFError, OSError, ValueError):
                continue
    threading.Thread(target=_drain, daemon=True).start()

    t0 = time.time()
    ticks = 0
    async for tick in feed.stream(symbol):
        ticks += 1
        await asyncio.to_thread(feed_q.put,
                                MarketEvent(tick=tick, event_id=f"EVT-{ticks}"))
    await asyncio.to_thread(feed_q.put, None)

    # wait for the pipeline to flush: telemetry exits on its sentinel
    deadline = t0 + 120
    for p in procs:
        remaining = max(0.0, deadline - time.time())
        p.join(timeout=remaining)
    alive = [p.name for p in procs if p.is_alive()]
    for p in procs:
        if p.is_alive():
            p.terminate()
    return {"ticks": ticks, "elapsed_s": round(time.time() - t0, 2),
            "procs": len(procs), "stuck": alive}
