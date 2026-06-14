from __future__ import annotations

from pathlib import Path

import pytest

from runtime.brokerage_redaction import (
    assert_no_raw_secret_after_redaction,
    assert_persisted_record_is_safe,
    keyed_account_fingerprint,
    persist_redacted_event,
    redact_nested_payload,
)
from runtime.security_scanner import scan_repo, scan_text


def test_repository_scanner_rejects_brokerage_credentials_and_account_ids() -> None:
    findings = scan_text("robinhood_access_token=rh_live_secret_value_123456 account_id=123456789")
    assert findings


def test_repository_scanner_rejects_statement_like_files(tmp_path: Path) -> None:
    (tmp_path / "my-robinhood-statement.pdf").write_text("fake", encoding="utf-8")
    findings = scan_repo(str(tmp_path))
    assert any("blocked_statement_or_screenshot_filename" in finding for finding in findings)


def test_runtime_ingestion_persists_only_safe_boundary_record() -> None:
    durable_sink: list[dict[str, str]] = []
    raw_event = {
        "source_label": "robinhood",
        "connection_id": "conn_123",
        "event_id": "evt_456",
        "account_id": "123456789",
        "positions": [{"symbol": "ABC", "quantity": 1}],
        "access_credential": "rh_live_secret_value_123456789",
    }

    record = persist_redacted_event(raw_event, durable_sink, secret_key="unit-test-key")

    assert durable_sink == [record]
    assert set(record) == {"source_label", "connection_id", "event_id", "account_fingerprint"}
    assert record["source_label"] == "robinhood"
    assert record["connection_id"] == "conn_123"
    assert record["event_id"] == "evt_456"
    assert record["account_fingerprint"].startswith("acctfp_")
    assert "123456789" not in str(durable_sink)
    assert "rh_live_secret" not in str(durable_sink)


def test_audit_log_assertion_reads_stored_record_not_ui_projection() -> None:
    durable_audit_log: list[dict[str, str]] = []
    persist_redacted_event(
        {
            "source_label": "robinhood",
            "connection_id": "conn_audit",
            "event_id": "evt_audit",
            "account_number": "999999999",
        },
        durable_audit_log,
        secret_key="unit-test-key",
    )

    stored_record = durable_audit_log[0]
    assert_persisted_record_is_safe(stored_record)
    assert "999999999" not in repr(stored_record)


def test_nested_payload_secret_redaction_is_not_key_name_only() -> None:
    raw_secret = "rh_nested_secret_value_abcdef123456"
    nested = {
        "outer": {
            "innocent_name": {
                "value": raw_secret,
                "deep": ["safe", {"not_secret_named": "account_number=123456789"}],
            }
        }
    }

    redacted = redact_nested_payload(nested)

    assert_no_raw_secret_after_redaction(redacted, [raw_secret, "123456789"])
    assert "[REDACTED]" in repr(redacted)


def test_keyed_digest_is_stable_and_not_plain_hash() -> None:
    first = keyed_account_fingerprint("123456789", "unit-test-key")
    second = keyed_account_fingerprint("123456789", "unit-test-key")
    different_key = keyed_account_fingerprint("123456789", "different-key")

    assert first == second
    assert first != different_key
    assert first.startswith("acctfp_")
    assert "123456789" not in first


def test_rejects_unsafe_persisted_record() -> None:
    with pytest.raises(AssertionError):
        assert_persisted_record_is_safe(
            {
                "source_label": "robinhood",
                "connection_id": "conn_1",
                "event_id": "evt_1",
                "account_fingerprint": "acctfp_safe",
                "account_id": "123456789",
            }
        )
