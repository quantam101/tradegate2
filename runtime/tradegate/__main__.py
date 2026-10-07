"""CLI: python -m runtime.tradegate {paper|backtest|optimize}"""

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

    elif mode == "sentiment":
        from .sentiment import main as sentiment_main
        sentiment_main(argv[1:])


    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
