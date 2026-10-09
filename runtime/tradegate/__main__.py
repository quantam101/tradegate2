"""CLI: python -m runtime.tradegate {paper|backtest|optimize|daily|rotation|...}"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .backtest import run_backtest, score
from .config import ConfigStore, EngineConfig
from .feed import ReplayFeed, SyntheticFeed
from .optimizer import tpe_search, walk_forward_windows


async def _agen_list(feed):
    return [t async for t in feed.stream()]


def _ticks(argv):
    steps = int(argv[argv.index("--steps") + 1]) if "--steps" in argv else 5000
    feed = (ReplayFeed(Path(argv[argv.index("--replay") + 1]))
            if "--replay" in argv else SyntheticFeed(steps=steps))
    return asyncio.run(_agen_list(feed))


def main(argv=None):
    argv = argv or sys.argv[1:]
    mode = argv[0] if argv else "backtest"

    if mode == "backtest":
        m = run_backtest(_ticks(argv))
        print(json.dumps(m, indent=2))

    elif mode == "optimize":
        ticks = _ticks(argv)
        windows = walk_forward_windows(ticks)
        base = EngineConfig()

        def objective(params):
            cfg = EngineConfig(**{**base.to_dict(), **params})
            scores, reports = [], []
            for train, test in windows:
                m = run_backtest(test, cfg)
                reports.append(m)
                scores.append(score(m, cfg, min_trades=5))
            return sum(scores) / len(scores), reports

        best_score, best, trials = tpe_search(objective, n_trials=16)
        out = Path("data/tradegate/engine_manifest.json")
        store = ConfigStore.from_manifest(out)
        store.swap(**best)
        print(json.dumps({"best_score": best_score, "best_params": best,
                          "trials": len(trials), "manifest": str(out)}, indent=2))

    elif mode == "paper":
        import os

        from .orchestrator import run_paper
        steps = int(argv[argv.index("--steps") + 1]) if "--steps" in argv else 5000
        kw = {"steps": steps,
              "audit_path": Path("data/tradegate/audit.jsonl"),
              "ledger_path": Path("data/tradegate/fills.jsonl"),
              "discord_url": os.environ.get("TRADEGATE_DISCORD_WEBHOOK"),
              "telegram_token": os.environ.get("TRADEGATE_TELEGRAM_TOKEN"),
              "telegram_chat": os.environ.get("TRADEGATE_TELEGRAM_CHAT")}
        asyncio.run(run_paper(**kw))

    elif mode == "daily":
        # Real-data paper run: daily OHLCV bars through the full mesh,
        # reported against buy-and-hold. This is the pre-live gate.
        from .daily import run_daily
        syms = (argv[argv.index("--symbols") + 1].split(",")
                if "--symbols" in argv else ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])
        cap = (float(argv[argv.index("--capital") + 1])
               if "--capital" in argv else 10000.0)
        run_daily(syms, capital=cap)

    elif mode == "procpaper":
        # Process-per-agent mesh: every stage in its own OS process.
        from .proc_orchestrator import run_procs
        steps = int(argv[argv.index("--steps") + 1]) if "--steps" in argv else 2000
        sym = argv[argv.index("--symbol") + 1] if "--symbol" in argv else "PAPER/USD"
        print(json.dumps(asyncio.run(run_procs(symbol=sym, steps=steps)), indent=2))

    elif mode == "livepaper":
        # 24/7 live paper trading: real Alpaca IEX trade stream → mesh →
        # AlpacaPaperBroker (server-side bracket exits). Requires
        # ALPACA_PAPER_KEY/SECRET; runs indefinitely until stopped.
        import os

        from .alpaca_broker import AlpacaPaperBroker
        from .alpaca_feed import AlpacaTradeFeed
        from .orchestrator import TradeGateOrchestrator, _TapFeed
        syms = (argv[argv.index("--symbols") + 1].split(",")
                if "--symbols" in argv else ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])
        cap = (float(argv[argv.index("--capital") + 1])
               if "--capital" in argv else 1000.0)
        orch = TradeGateOrchestrator(
            initial_capital=cap,
            ledger_path=Path("data/tradegate/fills.jsonl"),
            audit_path=Path("data/tradegate/audit.jsonl"),
            discord_url=os.environ.get("TRADEGATE_DISCORD_WEBHOOK"),
            telegram_token=os.environ.get("TRADEGATE_TELEGRAM_TOKEN"),
            telegram_chat=os.environ.get("TRADEGATE_TELEGRAM_CHAT"),
            broker=AlpacaPaperBroker())
        feed = _TapFeed(AlpacaTradeFeed(syms), orch.broker, orch.stages)
        asyncio.run(orch.run(feed))

    elif mode == "rotation":
        # Portfolio-level momentum rotation on real daily bars from a CSV
        # (symbol,date,open,high,low,close,volume). Trades from --start.
        from .rotation import RotationConfig, buy_and_hold, load_csv, run_rotation
        if "--csv" not in argv:
            print("rotation requires --csv PATH")
            sys.exit(1)
        data = load_csv(Path(argv[argv.index("--csv") + 1]))
        cap = (float(argv[argv.index("--capital") + 1])
               if "--capital" in argv else 1000.0)
        start = argv[argv.index("--start") + 1] if "--start" in argv else None
        end = argv[argv.index("--end") + 1] if "--end" in argv else None
        res = run_rotation(data, RotationConfig(), capital=cap, start=start, end=end)
        first = res.equity[0][0]
        out = res.metrics()
        out["window"] = {"from": first, "to": res.equity[-1][0]}
        out["equal_weight_buy_hold_roi"] = buy_and_hold(data, list(data), first, end)
        out["final_holdings"] = res.holdings[-1][1] if res.holdings else {}
        print(json.dumps(out, indent=2))

    elif mode == "rotation-paper":
        # Daily real-data paper run of the rotation; --execute places orders
        # on the Alpaca PAPER account when ALPACA_PAPER_KEY/SECRET are set.
        from .rotation_paper import main as rotation_paper_main
        rotation_paper_main(argv[1:])

    elif mode == "sentiment":
        from .sentiment import main as sentiment_main
        sentiment_main(argv[1:])


    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
