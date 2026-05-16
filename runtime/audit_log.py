from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor: str
    action: str
    status: str
    details: Dict[str, Any]
    correlation_id: Optional[str] = None
    timestamp: float = time.time()


class AuditLog:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or os.getenv("GMAOS_AUDIT_LOG", "./data/audit.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["timestamp"] = time.time()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")

    def info(self, actor: str, action: str, details: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        self.write(AuditEvent("info", actor, action, "ok", details, correlation_id))

    def blocked(self, actor: str, action: str, details: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        self.write(AuditEvent("policy", actor, action, "blocked", details, correlation_id))

    def error(self, actor: str, action: str, details: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        self.write(AuditEvent("error", actor, action, "error", details, correlation_id))
