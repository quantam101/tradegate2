"""Sentiment & Macro agent's score source.

Two layers, both free:

1. ``score_headlines(headlines)`` — offline lexicon scorer (the always-on
   fallback). Runs the headline list through a weighted bullish/bearish
   finance lexicon and returns a score in [-1, 1]. Deterministic, tested.
2. ``refresh(headlines, out_path)`` — if any free LLM key is set
   (``GROQ_API_KEY`` / ``OPENROUTER_API_KEY``), asks the model for a
   market-sentiment score, clamps to [-1, 1], and writes
   ``data/tradegate/sentiment.json``. Falls back to the lexicon when no
   key exists or the call fails — the file always lands.

The mesh's ``SentimentAgent`` reads the file; a missing/corrupt file
means neutral 0.0, so sentiment can only *help*, never break, the mesh.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("tradegate")
import os
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

SENTIMENT_PATH = Path("data/tradegate/sentiment.json")

# Weighted finance lexicon — small, auditable, honest about its limits.
_BULL = {"beat": 2, "surge": 2, "rally": 2, "record": 1.5, "upgrade": 1.5,
         "growth": 1, "profit": 1.5, "beat expectations": 3, "cut rates": 2,
         "stimulus": 2, "deal": 1, "approval": 1.5, "buyback": 2, "soar": 2,
         "rebound": 1.5, "outperform": 1.5, "bullish": 2, "hires": 1,
         "raises guidance": 2.5, "strong": 1, "recovery": 1.5}
_BEAR = {"miss": 2, "plunge": 2, "crash": 3, "downgrade": 1.5, "layoffs": 2,
         "recession": 2.5, "default": 3, "fraud": 3, "probe": 2, "ban": 2,
         "halt": 1.5, "fine": 1.5, "bankruptcy": 3, "bearish": 2, "fear": 1,
         "cuts guidance": 2.5, "weak": 1, "slowdown": 2, "selloff": 2,
         "liquidity crisis": 3, "rate hike": 1.5, "inflation surges": 2,
         "warning": 1.5, "loss": 1.5}


def score_headlines(headlines: Iterable[str]) -> float:
    """Lexicon score in [-1, 1]: tanh of net weighted hits / 6."""
    import math
    net = 0.0
    for h in headlines:
        t = h.lower()
        net += sum(w for k, w in _BULL.items() if k in t)
        net -= sum(w for k, w in _BEAR.items() if k in t)
    return math.tanh(net / 6.0)


def _llm_score(headlines: list[str]) -> float | None:
    """Free LLM chain → a single score. None if no key / all fail."""
    prompt = ("Rate the aggregate market sentiment of these headlines on a "
              "scale from -1.0 (extremely bearish) to +1.0 (extremely "
              "bullish). Reply with ONLY the number.\n\n" +
              "\n".join(f"- {h}" for h in headlines[:20]))
    providers = [
        ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions",
         "llama-3.3-70b-versatile"),
        ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions",
         "meta-llama/llama-3.3-70b-instruct:free"),
    ]
    for env, url, model in providers:
        key = os.getenv(env, "").strip()
        if not key:
            continue
        try:
            body = json.dumps({"model": model, "max_tokens": 10,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = json.loads(r.read())["choices"][0]["message"]["content"]
            import re
            m = re.search(r"-?\d+(?:\.\d+)?", txt)
            if m:
                return max(-1.0, min(1.0, float(m.group())))
        except (OSError, ValueError, KeyError, IndexError) as e:
            log.debug("llm score attempt failed: %s", e)
            continue
    return None


def refresh(headlines: Iterable[str], out_path: Path = SENTIMENT_PATH,
            source: str = "cli") -> dict:
    """Score headlines (LLM first, lexicon backstop) and write the file."""
    heads = list(headlines)
    llm = _llm_score(heads)
    score = llm if llm is not None else score_headlines(heads)
    doc = {"score": round(score, 4), "n_headlines": len(heads),
           "method": "llm" if llm is not None else "lexicon",
           "source": source, "ts": time.time()}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2))
    return doc


def load(path: Path = SENTIMENT_PATH) -> float:
    """Latest score in [-1,1]; 0.0 on missing/corrupt/stale (>48h) file."""
    try:
        doc = json.loads(path.read_text())
        if time.time() - doc.get("ts", 0) > 48 * 3600:
            return 0.0
        return max(-1.0, min(1.0, float(doc.get("score", 0.0))))
    except (OSError, ValueError, TypeError):
        return 0.0


def main(argv=None) -> None:
    """CLI: python -m runtime.tradegate.sentiment "headline one" "headline two"
    or --file headlines.txt (one headline per line)."""
    import sys
    argv = list(argv if argv is not None else sys.argv[1:])
    out = SENTIMENT_PATH
    if "--out" in argv:
        i = argv.index("--out")
        out = Path(argv[i + 1])
        del argv[i:i + 2]
    if argv and argv[0] == "--file":
        heads = [l.strip() for l in Path(argv[1]).read_text().splitlines() if l.strip()]
    else:
        heads = argv
    doc = refresh(heads, out)
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
