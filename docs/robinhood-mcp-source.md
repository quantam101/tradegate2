# Robinhood MCP source policy

TradeGate treats Robinhood MCP as a **proposal-only public-source feed**. It is not an execution connector.

## Current authorization boundary

- TradeGate may read public, timestamped market or research sources and record a trade proposal.
- TradeGate must not collect Robinhood credentials, tokens, account IDs, statements, screenshots, or exports.
- TradeGate must not submit any order or call a live/paper brokerage mutation endpoint.
- Future execution requires a separate explicit approval after at least 30 audited proposal-only dry runs.
- The emergency kill switch lives at `POST /api/robinhood/kill-switch` and blocks new proposals while active.
- Proposal and kill-switch APIs require an authenticated command-center session.
- Runtime state persists under `GMAOS_DATA_DIR` (`/data` in Docker, `./data` locally).

## Proposal card contract

Every proposal must include:

- `symbol` — public-market ticker
- `side` — `buy` or `sell`
- `asset_class` — currently only `equity`
- `order_type` — currently only `limit`; market orders are blocked
- `quantity`
- `limit_price`
- `stop_loss`
- `max_loss_usd`
- `expires_at` — ISO timestamp, maximum TTL 24 hours
- `thesis`
- `source_url` — optional HTTPS source URL

The API rejects expired proposals, missing stop/max-loss fields, market orders, unsupported asset classes, and any payload containing credential/account identifier material.

## Stored record

Accepted proposals are appended to `robinhood-proposals.jsonl` under `GMAOS_DATA_DIR` with:

- `status: proposal_only`
- `execution: blocked_until_future_explicit_approval`
- `risk_review_required: true`

## Risk review checklist

Before any proposal is considered for manual review, verify:

1. Public source is reachable and timestamped.
2. Symbol and asset class are supported.
3. Limit price, stop loss, and max loss are present.
4. Proposal is unexpired.
5. No credential or account identifier is stored.
6. No execution is attempted without future explicit approval.
