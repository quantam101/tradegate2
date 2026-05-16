from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reason: str


class Verifier:
    BLOCKED_MARKERS = ["API_KEY=", "BEGIN PRIVATE KEY", "sk-", "password:", "token:"]

    def verify_text_output(self, output: str) -> VerificationResult:
        if not output or not output.strip():
            return VerificationResult(False, "empty_output")
        lowered = output.lower()
        for marker in self.BLOCKED_MARKERS:
            if marker.lower() in lowered:
                return VerificationResult(False, f"possible_secret_leak:{marker}")
        return VerificationResult(True, "verified")
