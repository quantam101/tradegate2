from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ComplexityResult:
    score: float
    reason: str


class ComplexityScorer:
    HIGH_RISK_TERMS = {
        "deploy", "payment", "stripe", "send email", "delete", "production", "merge", "purchase",
        "client", "legal", "tax", "password", "secret", "token", "api key", "bank"
    }

    def score(self, objective: str, context: str = "") -> ComplexityResult:
        text = f"{objective} {context}".lower()
        words = re.findall(r"[a-z0-9_]+", text)
        base = min(len(words) / 1000.0, 0.45)
        risk_hits = [term for term in self.HIGH_RISK_TERMS if term in text]
        risk = min(len(risk_hits) * 0.12, 0.55)
        score = min(base + risk, 1.0)
        reason = "risk_terms=" + ",".join(risk_hits) if risk_hits else "low_static_complexity"
        return ComplexityResult(score=round(score, 4), reason=reason)
