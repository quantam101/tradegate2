# TradeGate momentum rotation

`runtime/tradegate/rotation.py` is a portfolio-level strategy for daily bars.
It replaces the tick-microstructure mesh for daily trading, because that mesh
has no edge on daily data.

## Rules

Every 21 trading days:

1. Rank all assets by their trailing 189-day return.
2. Drop any asset whose trailing return is negative (absolute momentum).
3. Drop any asset whose close is below its 100-day moving average (trend filter).
4. Hold the top 4 survivors, weighted by inverse 63-day volatility.
5. If nothing survives, hold cash.

The target is computed from closes through day *t* and fills at day *t+1*'s
open. Every traded dollar costs 5 bps.

## How the defaults were chosen

The universe has 10 symbols: SPY, QQQ, IWM, GLD, TLT, IBIT (Bitcoin), ETHA
(Ether), FXE (euro), FXY (yen) and UUP (dollar). Prices are real daily bars.

- **Design window:** Apr 2024 – Apr 8, 2026. A 144-config grid was run over
  lookback, top-K, SMA, rebalance frequency and weighting. The defaults were
  picked on that window only, using best median Sharpe and smallest drawdown.
  Holding 4 assets, a 100-day SMA and monthly rebalancing won.
- **Forward test (unseen):** Apr 9 – Oct 8, 2026, starting with $1,000.

| Strategy (forward test) | End value | Return | Max drawdown | Win rate |
|---|---|---|---|---|
| **Rotation (defaults)** | **$1,071.97** | **+7.2%** | 4.6% | 87% (15 round trips) |
| Equal-weight buy & hold, same 10 assets | $1,051 | +5.1% | — | — |
| SPY buy & hold | $1,147 | +14.7% | 4.5% | — |
| Old agent mesh, same 10 assets | $983 | −1.7% | 2.8% | 32% |

Neighbouring configs (lookback 126/189, equal or inverse-vol weighting)
returned between +7.2% and +13.6% on the forward window. Across the whole grid
the median forward return was +4.2%, and 97 of 144 configs were positive.
None of the 144 beat SPY in this window, which was a strong US-equity tape.

## Run it

```bash
python -m runtime.tradegate rotation --csv prices.csv --capital 1000 --start 2026-04-09
```

The CSV columns are `symbol,date,open,high,low,close,volume`, with daily bars.

## Limits

- Six months of forward data is a small sample. The result could be luck.
- Crypto and forex are tested through ETFs, which trade only during regular
  US market hours.
- No live execution path is wired yet. Run it paper-only first.
