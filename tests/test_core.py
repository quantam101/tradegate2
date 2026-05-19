import os
from pathlib import Path

import yaml

from runtime.sovereign_core import SovereignAutomationCore


def test_core_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAOS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("GMAOS_APPROVAL_DB", str(tmp_path / "approvals.json"))
    monkeypatch.setenv("GMAOS_VECTOR_CACHE", str(tmp_path / "vector.sqlite3"))
    monkeypatch.setenv("GMAOS_EMBEDDING_DIM", "4")
    core = SovereignAutomationCore()
    result = core.execute("system", "context", "Create a local draft", [0.1, 0.1, 0.1, 0.1])
    assert result.status == "ok"
    assert result.route_tier == "DETERMINISTIC_LOCAL"


def test_complex_work_requires_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAOS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("GMAOS_APPROVAL_DB", str(tmp_path / "approvals.json"))
    monkeypatch.setenv("GMAOS_VECTOR_CACHE", str(tmp_path / "vector.sqlite3"))
    monkeypatch.setenv("GMAOS_EMBEDDING_DIM", "4")
    core = SovereignAutomationCore()
    result = core.execute("system", "context", "Deploy production and send client email", [0.2, 0.2, 0.2, 0.2])
    assert result.status == "approval_required"


def test_scaffold_modules_are_not_enabled():
    for path in Path("modules").glob("*/module.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))["module"]
        if data["state"] == "scaffold" or data["state"].endswith("_scaffold"):
            assert data["enabled"] is False
            assert data.get("healthcheck") is None
