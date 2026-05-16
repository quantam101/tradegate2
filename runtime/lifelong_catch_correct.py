from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


class LifelongCatchCorrect:
    def __init__(self, path: str = "./data/corrections.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, category: str, issue: str, correction: str, metadata: Dict[str, Any] | None = None) -> None:
        payload = {
            "timestamp": time.time(),
            "category": category,
            "issue": issue,
            "correction": correction,
            "metadata": metadata or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
