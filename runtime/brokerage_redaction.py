from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

_SECRET_VALUE_PATTERNS = (
    re.compile(r"rh_[A-Za-z0-9_\-]{12,}", re.IGNORECASE),
    re.compile(r"(?:access|refresh|brokerage|robinhood)[_-]?credential\s*[:=]\s*[^\s,;}]+", re.IGNORECASE),
    re.compile(r"\b(?:acct|account)[_-]?(?:id|number)?\s*[:=]\s*[0-9A-Za-z\-]{6,}", re.IGNORECASE),
)

_SECRET_KEY_MARKERS = frozenset(
    {
        "token",
        "credential",
        "secret",
        "password",
        "account_id",
        "account_number",
        "brokerage_account",
        "raw_account",
        "statement",
        "screenshot",
    }
)

_ALLOWED_PERSISTED_KEYS = frozenset({"source_label", "connection_id", "event_id", "account_fingerprint"})
_REDACTED = "[REDACTED]"
_DEFAULT_LOCAL_KEY = "tradegate-local-redaction-test-key"


@dataclass(frozen=True, slots=True)
class RedactedBrokerageEvent:
    source_label: str
    connection_id: str
    event_id: str
    account_fingerprint: str

    def to_persisted_record(self) -> Dict[str, str]:
        return {
            "source_label": self.source_label,
            "connection_id": self.connection_id,
            "event_id": self.event_id,
            "account_fingerprint": self.account_fingerprint,
        }


def _canonical(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def keyed_account_fingerprint(identifier: str, secret_key: str | None = None) -> str:
    """Return a stable, non-guessable account fingerprint for correlation."""

    key = secret_key or os.getenv("TRADEGATE_REDACTION_KEY") or _DEFAULT_LOCAL_KEY
    digest = hmac.new(key.encode("utf-8"), identifier.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"acctfp_{digest[:24]}"


def contains_secret_like_value(value: Any) -> bool:
    text = _canonical(value)
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


def _key_is_sensitive(key: Any) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def redact_nested_payload(value: Any) -> Any:
    """Recursively redact sensitive brokerage material regardless of key name."""

    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if _key_is_sensitive(key) or contains_secret_like_value(item) else redact_nested_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_nested_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_nested_payload(item) for item in value)
    return _REDACTED if contains_secret_like_value(value) else value


def build_persistable_brokerage_event(raw_event: Mapping[str, Any], *, secret_key: str | None = None) -> RedactedBrokerageEvent:
    """Create the only allowed durable record for brokerage ingestion."""

    source_label = str(raw_event.get("source_label") or "brokerage")
    connection_id = str(raw_event.get("connection_id") or raw_event.get("connectionId") or "unknown_connection")
    event_id = str(raw_event.get("event_id") or raw_event.get("eventId") or "unknown_event")
    raw_identifier = str(
        raw_event.get("account_id")
        or raw_event.get("accountId")
        or raw_event.get("account_number")
        or raw_event.get("accountNumber")
        or f"{source_label}:{connection_id}:{event_id}"
    )
    return RedactedBrokerageEvent(
        source_label=source_label,
        connection_id=connection_id,
        event_id=event_id,
        account_fingerprint=keyed_account_fingerprint(raw_identifier, secret_key),
    )


def assert_persisted_record_is_safe(record: Mapping[str, Any]) -> None:
    disallowed = set(record) - _ALLOWED_PERSISTED_KEYS
    if disallowed:
        raise AssertionError(f"durable record contains disallowed keys: {sorted(disallowed)}")
    for key, value in record.items():
        if key != "account_fingerprint" and contains_secret_like_value(value):
            raise AssertionError(f"durable record contains secret-like value in {key}")
    fingerprint = str(record.get("account_fingerprint", ""))
    if not fingerprint.startswith("acctfp_"):
        raise AssertionError("durable record missing keyed account fingerprint")


def persist_redacted_event(raw_event: Mapping[str, Any], sink: list[Dict[str, str]], *, secret_key: str | None = None) -> Dict[str, str]:
    """Persistence boundary helper used by runtime code and tests."""

    record = build_persistable_brokerage_event(raw_event, secret_key=secret_key).to_persisted_record()
    assert_persisted_record_is_safe(record)
    sink.append(record)
    return record


def assert_no_raw_secret_after_redaction(redacted_payload: Any, forbidden_values: Iterable[str]) -> None:
    serialized = _canonical(redacted_payload)
    for value in forbidden_values:
        if value and value in serialized:
            raise AssertionError("raw secret survived nested redaction")
