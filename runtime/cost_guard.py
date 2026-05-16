from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Any


class CostGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteDecision:
    tier: str
    endpoint: str | None
    estimated_cost_usd: float
    action: str
    paid: bool = False


class CostGuard:
    def __init__(self) -> None:
        self.mode = os.getenv("GMAOS_MODE", "strict_zero_spend")
        self.paid_enabled = os.getenv("GMAOS_PAID_ADAPTERS_ENABLED", "false").lower() == "true"
        self.max_cost = float(os.getenv("GMAOS_MAX_COST_USD", "0"))

    def assert_allowed(self, route: RouteDecision) -> None:
        if self.mode == "strict_zero_spend":
            if route.paid or route.estimated_cost_usd > 0:
                raise CostGuardError(
                    f"Blocked paid route in strict_zero_spend mode: action={route.action}, cost={route.estimated_cost_usd}"
                )
            if route.tier.upper().startswith("PAID") or route.tier.upper().startswith("EXTERNAL_PAID"):
                raise CostGuardError(f"Blocked paid tier: {route.tier}")
        if route.estimated_cost_usd > self.max_cost:
            raise CostGuardError(f"Route cost exceeds ceiling: {route.estimated_cost_usd} > {self.max_cost}")
        if route.paid and not self.paid_enabled:
            raise CostGuardError("Paid adapters are disabled.")

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "paid_adapters_enabled": self.paid_enabled,
            "max_cost_usd": self.max_cost,
            "fail_closed": True,
        }
