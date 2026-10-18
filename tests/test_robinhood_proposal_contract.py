from __future__ import annotations

from pathlib import Path
import json

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_registry_has_unique_workmarket_and_robinhood_proposal_only() -> None:
    raw = (ROOT / "connectors/registry.yaml").read_text(encoding="utf-8")
    assert raw.count("workmarket_adp:") == 1
    connectors = yaml.safe_load(raw)["connectors"]
    rh = connectors["robinhood_mcp"]
    assert rh["state"] == "proposal_only"
    assert rh["execution_enabled"] is False
    assert "create_trade_proposal" in rh["permissions"]
    assert rh["kill_switch_url"] == "/api/robinhood/kill-switch"


def test_robinhood_contract_blocks_execution_sensitive_paths() -> None:
    contract = yaml.safe_load((ROOT / "connectors/robinhood-mcp.yaml").read_text(encoding="utf-8"))["connector"]
    assert contract["mode"] == "proposal_only"
    assert contract["execution_enabled"] is False
    assert contract["credential_collection"] == "forbidden"
    assert contract["supported_asset_classes"] == ["equity"]
    assert "market" in contract["blocked_order_types"]
    required = set(contract["required_proposal_fields"])
    assert {"stop_loss", "max_loss_usd", "expires_at", "limit_price"}.issubset(required)
    assert contract["limits"]["min_dry_run_proposals_before_execution_review"] == 30


def test_policy_requires_future_execution_approval() -> None:
    policy = yaml.safe_load((ROOT / "approvals/policy.yaml").read_text(encoding="utf-8"))
    required = set(policy["always_requires_approval"])
    assert "brokerage_live_execution" in required
    assert "brokerage_credential_collection" in required
    assert "market_order_submission" in required
    assert "unsupported_asset_trade" in required


def test_robinhood_docs_define_no_trade_boundary() -> None:
    text = (ROOT / "docs/robinhood-mcp-source.md").read_text(encoding="utf-8").lower()
    assert "proposal-only" in text
    assert "must not collect robinhood credentials" in text
    assert "must not submit any order" in text
    assert "30 audited proposal-only dry runs" in text


def test_robinhood_feed_descriptor_is_proposal_only() -> None:
    feed = json.loads((ROOT / "data/feeds/robinhood-mcp-trading.json").read_text(encoding="utf-8"))
    assert feed["source_id"] == "robinhood_mcp"
    assert feed["state"] == "proposal_only"
    assert feed["authorization"] == "not_granted"
    assert feed["execution_enabled"] is False
    assert feed["credential_collection"] == "forbidden"
    assert feed["write_permissions"] == []
    assert "market_context" in feed["read_permissions"]


def test_rejected_robinhood_actions_are_audited_without_payloads() -> None:
    route = (ROOT / "app/api/robinhood/proposals/route.ts").read_text(encoding="utf-8")
    assert "robinhood-rejections.jsonl" in route
    assert "event: 'security_rejection'" in route
    assert "recordRejection('kill_switch_active'" in route
    assert "recordRejection('invalid_proposal'" in route
    assert "submitted" not in route.lower() or "submitted payload" not in route.lower()
