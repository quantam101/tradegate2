from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict


class ApprovalRequired(RuntimeError):
    pass


class ApprovalGate:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("GMAOS_APPROVAL_DB", "./data/approvals.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load(self) -> Dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def require(self, action: str, reason: str, payload: Dict[str, Any]) -> str:
        approvals = self._load()
        approval_id = f"approval-{int(time.time() * 1000)}"
        approvals[approval_id] = {
            "action": action,
            "reason": reason,
            "payload": payload,
            "status": "pending",
            "created_at": time.time(),
        }
        self._save(approvals)
        raise ApprovalRequired(f"Approval required: {approval_id} for action={action}")

    def is_approved(self, approval_id: str) -> bool:
        approvals = self._load()
        return approvals.get(approval_id, {}).get("status") == "approved"
