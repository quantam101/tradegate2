# TradeGate ProfitEngine — Stateful Micro-Agent Mesh

Paper-trading implementation of the v5.0 architecture: nine single-purpose
asyncio agents connected by non-blocking queues, a paper broker, honest
replay backtesting, and walk-forward parameter optimization.

**Live trading is not implemented.** `Broker` and `MarketDataSource` are
interfaces; only `PaperBroker`, `ReplayFeed`, and `SyntheticFeed` ship.
An `ExchangeWebSocketFeed` stub marks the seam for a future live adapter
(needs exchange credentials + approval gates — `modules/tradegate` already
declares `requires_approval_for: external_write, paid_call, production_change`).

## Agent pipeline

```
feed → A1 ingest → A2 depth/CVD → A3 regime → A4 alpha / A5 beta
     → A6 risk (fractional Kelly + drawdown breaker)
     → A7 execution (PaperBroker) → A8 telemetry → A9 WFO optimizer
```

- **A2** computes bid/ask depth imbalance and running CVD per tick.
- **A3** classifies regime with rolling ATR + return-volatility context
  (`LIQUIDITY_SWEEP_BREAKOUT`, `MEAN_REVERSION_RANGE`, `NOISE_LOW_EDGE`).
- **A6** sizes `equity × kelly × safety_factor`, capped at
  `equity × max_trade_fraction`, and **halts the pipeline** when realized
  equity drawdown ≥ `max_drawdown_limit` (4% default).
- **A7** submits orders; `PaperBroker` applies ATR **trailing** stops,
  take-profits, a 1bp fee model, and an append-only fill ledger.
- **A8** fans out to an audit JSONL and (optionally) Discord/Telegram via
  `asyncio.to_thread` — never blocking the hot path.
- **A9** runs `optimizer.tpe_search` (a small stdlib TPE-style sampler)
  over real out-of-sample backtest windows and hot-swaps config
  atomically through `ConfigStore.swap()` — versioned, immutable
  snapshots; no shared mutable state.

## Usage

```bash
python3 -m runtime.tradegate backtest [--replay ticks.jsonl] [--steps N]
python3 -m runtime.tradegate optimize [--replay ticks.jsonl]
python3 -m runtime.tradegate paper
```

`paper` writes `data/tradegate/fills.jsonl` (ledger) and
`data/tradegate/audit.jsonl` (telemetry). `optimize` writes the winning
manifest to `data/tradegate/engine_manifest.json`.

Environment: `TRADEGATE_DISCORD_WEBHOOK`, `TRADEGATE_TELEGRAM_TOKEN`,
`TRADEGATE_TELEGRAM_CHAT` (all optional).

## Daemon deployment (OCI / Ubuntu 24.04)

```bash
sudo cp deploy/tradegate.service /etc/systemd/system/
sudo chown -R ubuntu:ubuntu /home/ubuntu/tradegate2
sudo systemctl daemon-reload
sudo systemctl enable --now tradegate.service
sudo systemctl status tradegate.service
```

## Honesty notes vs the original spec

The spec's reference script simulated fills (`asyncio.sleep(0.0008)`),
hard-coded P&L, and "optimized" a hand-authored curve. This implementation
instead: computes real exits through the broker on every tick, derives all
metrics from the fill ledger, optimizes against out-of-sample windows, and
reports losses truthfully — expect negative ROI on random-walk feeds.
The `TradeGateOrchestrator`/backtester flush the mesh per tick so exit
checks can't race signal execution.
