# Deploying TradeGate live-paper to Render

The `livepaper` mode runs the full 9-agent mesh against Alpaca's free
real-time IEX trade stream, with orders going to Alpaca's **paper**
endpoint (no real money — `paper-api.alpaca.markets`; the live endpoint
is unreachable in this build).

## Prereqs

1. Free Alpaca paper account → get `ALPACA_PAPER_KEY` / `ALPACA_PAPER_SECRET`
   (paper dashboard, not live).
2. Render account. `render.yaml` in the repo root defines a
   `tradegate-livepaper` background worker — Render picks it up via
   **New → Blueprint**.

## Steps

1. Render dashboard → New → Blueprint → select this repo.
2. Set `ALPACA_PAPER_KEY` and `ALPACA_PAPER_SECRET` as env vars on the
   `tradegate-livepaper` service (marked `sync: false` in render.yaml —
   they never live in git).
3. Deploy. The worker streams trades, runs the mesh, and records fills
   to the attached disk at `data/tradegate/fills.jsonl` + `audit.jsonl`.

## Honest operating notes

- **Cost**: a 24/7 worker needs a paid Render plan (starter ≈ $7/mo).
  The zero-spend alternative already exists: the GitHub Actions weekday
  cron (`tradegate-paper.yml`) runs the same mesh on daily bars and
  commits a benchmark ledger — it's just not intraday.
- **Exits**: entries/exits are Alpaca server-side brackets — positions
  close even while the worker is down or restarting.
- **Breaker**: AlpacaPaperBroker tracks positions, not the in-process
  drawdown breaker — the 4% breaker applies to PaperBroker runs; the
  RiskAgent still gates every entry.
- **Depth/sweeps**: IEX trades carry no book depth, so
  `LIQUIDITY_SWEEP_BREAKOUT` can never fire live — entries come from the
  momentum/RSI regime path only. Nothing is faked to look like depth.
- First deploys should run with `--capital` equal to what you'd actually
  risk — the fill ledger is the honest record.
