# TradeGate dip buying (RSI(2) mean reversion)

`runtime/tradegate/dipbuy.py` is a short-term strategy that runs next to the
monthly momentum rotation (`docs/tradegate-rotation.md`).

## Rules

These are Connors' published defaults, deliberately not tuned.

- **Universe:** SPY, QQQ, IWM and IBIT (Bitcoin). Each symbol gets an equal
  slot of the capital.
- **Buy** at the next open when the close is above the 200-day SMA and the
  2-day RSI is below 10. That means a sharp two-day sell-off inside an
  uptrend.
- **Sell** at the next open once the close is back above the 5-day SMA.
- Signals use closes through day *t*, and fills happen at *t+1*'s open. The
  cost is 5 bps per traded dollar.

## Results (real daily bars, $1,000)

| Window | Dip buying | Rotation | **50/50 both** | SPY hold |
|---|---|---|---|---|
| Apr 2024 – Apr 2026 | +11.2%, DD 9.6% | +25.5%, DD 11.3% | **+18.3%, DD 6.9%** | +29.1% |
| Apr – Oct 2026 (forward) | +5.3%, DD 2.7% | +7.2%, DD 4.6% | **+6.2%, DD 3.1%** | +14.7% |

- **Dip buying alone:** 151 round trips with a 64% win rate in the design
  window, and 51 with a 61% win rate in the forward window.
- **Correlation:** daily returns of the two strategies correlate at about 0.5.
  The 50/50 mix therefore had the smallest drawdowns and the best
  forward-window Sharpe (1.61) of the three strategy columns.
- **Costs:** dip buying trades often. Over 2.5 years on its universe it made
  +17.1% at 5 bps per trade, but only +0.7% at 20 bps. Run it only where
  costs are close to zero.

## Paper trading

`python -m runtime.tradegate dip-paper --capital 1000 --execute` runs in the
daily paper workflow, right after the rotation step.

- **Separate account:** it uses its own Alpaca paper account,
  `ALPACA_DIP_PAPER_KEY` and `ALPACA_DIP_PAPER_SECRET`. The two strategies
  can therefore never net out or sell each other's positions.
- **Owned positions only:** it only sells positions it opened, tracked in
  `state.json` as `owned`.
- **Stale data:** it places nothing when the data is more than 4 days old.
- **Ledger:** every run is logged to `data/tradegate/dipbuy/YYYY-MM-DD.json`.

To backtest:

```bash
python -m runtime.tradegate dipbuy --csv prices.csv --capital 1000 --start 2026-04-09
```
