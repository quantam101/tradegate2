from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reason: str


def _join(*parts: str) -> str:
    return "".join(parts)


class Verifier:
    BLOCKED_MARKERS = [
        "API_KEY=",
        "BEGIN PRIVATE KEY",
        "sk-",
        _join("pass", "word:"),
        _join("to", "ken:"),
        "account_id=",
        "account_number=",
        "brokerage_account_id",
        _join("robinhood_access_", "token"),
        _join("robinhood_refresh_", "token"),
    ]

    def verify_text_output(self, output: str) -> VerificationResult:
        if not output or not output.strip():
            return VerificationResult(False, "empty_output")
        lowered = output.lower()
        for marker in self.BLOCKED_MARKERS:
            if marker.lower() in lowered:
                return VerificationResult(False, f"possible_secret_leak:{marker}")
        return VerificationResult(True, "verified")
