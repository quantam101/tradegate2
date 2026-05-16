from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .cost_guard import RouteDecision


@dataclass(frozen=True)
class ModelRoute:
    decision: RouteDecision
    reason: str


class LocalModelRouter:
    def route(self, complexity_score: float) -> ModelRoute:
        local_enabled = os.getenv("GMAOS_LOCAL_MODEL_ENABLED", "false").lower() == "true"
        local_endpoint = os.getenv("GMAOS_LOCAL_MODEL_ENDPOINT", "http://localhost:11434/v1/chat/completions")

        if complexity_score <= 0.35:
            return ModelRoute(RouteDecision("DETERMINISTIC_LOCAL", None, 0.0, "deterministic_execution"), "low_complexity")
        if complexity_score <= 0.60 and local_enabled:
            return ModelRoute(RouteDecision("LOCAL_MODEL", local_endpoint, 0.0, "local_inference"), "local_model_allowed")
        return ModelRoute(
            RouteDecision("HUMAN_REVIEW_QUEUE", None, 0.0, "approval_required", paid=False),
            "complex_or_model_unavailable_queued_for_review",
        )
