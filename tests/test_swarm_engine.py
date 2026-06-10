import asyncio

import pytest

from runtime.cost_guard import CostGuard
from runtime.swarm_engine import (
    AutonomousSwarmOrchestrator,
    DeclarativeExecutionPlan,
    DistributedExecutionMatrix,
    FailoverInferenceGateway,
    MetricAssertion,
    SecurityEnforcer,
    SecurityError,
)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAOS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("GMAOS_MODE", "strict_zero_spend")
    monkeypatch.setenv("GMAOS_PAID_ADAPTERS_ENABLED", "false")


def test_metric_assertion_rejects_unknown_type():
    with pytest.raises(ValueError):
        MetricAssertion(column="revenue", assertion_type="not_a_real_type")


def test_plan_from_dict_parses_assertions():
    plan = DeclarativeExecutionPlan.from_dict(
        {
            "analytical_rationale": "r",
            "pure_python_script": "print('ok')",
            "data_quality_assertions": [
                {"column": "revenue", "assertion_type": "not_null", "parameters": {}}
            ],
        }
    )
    assert plan.pure_python_script == "print('ok')"
    assert len(plan.data_quality_assertions) == 1
    assert plan.data_quality_assertions[0].column == "revenue"


def test_security_enforcer_blocks_prohibited_signatures():
    for bad in ["import os", "import sys", "subprocess.run('x')", "eval('1')", "open('/etc/passwd')"]:
        with pytest.raises(SecurityError):
            SecurityEnforcer.verify_and_inject(bad, [])


def test_security_enforcer_strips_fences_and_injects_assertions():
    code = "```python\nx = 1\n```"
    hardened = SecurityEnforcer.verify_and_inject(
        code, [MetricAssertion(column="revenue", assertion_type="not_null")]
    )
    assert "import pandas as pd" in hardened
    assert "x = 1" in hardened
    assert "AUTOMATED INVARIANT ASSERTIONS" in hardened
    assert "df['revenue'].isnull().sum() == 0" in hardened


def test_assertion_block_rejects_non_numeric_range_bound():
    # Code injection via a crafted "min" parameter must be rejected, not interpolated.
    malicious = MetricAssertion(
        column="revenue",
        assertion_type="range_bound",
        parameters={"min": "0\nimport os\nos.system('id')\n#"},
    )
    with pytest.raises(SecurityError):
        SecurityEnforcer.verify_and_inject("x = 1", [malicious])


def test_assertion_block_rejects_boolean_range_bound():
    with pytest.raises(SecurityError):
        SecurityEnforcer.verify_and_inject(
            "x = 1",
            [MetricAssertion(column="c", assertion_type="range_bound", parameters={"max": True})],
        )


def test_assertion_block_escapes_malicious_column_name():
    # A column name that tries to break out of the error-message string literal
    # must be repr-escaped, never producing a bare executable statement.
    evil_col = "x'\ndanger = 1\n#"
    hardened = SecurityEnforcer.verify_and_inject(
        "y = 1", [MetricAssertion(column=evil_col, assertion_type="not_null")]
    )
    # The injected assignment must not appear as its own line of code.
    assert "\ndanger = 1\n" not in hardened
    # The assembled program is still syntactically valid Python.
    compile(hardened, "<hardened>", "exec")


def test_prohibited_token_in_column_is_neutralized_as_string_literal():
    # A prohibited signature smuggled via a column name is rendered inert: repr
    # escapes the newline so it stays inside a single string literal and never
    # becomes an executable statement.
    hardened = SecurityEnforcer.verify_and_inject(
        "y = 1",
        [MetricAssertion(column="a\nimport os\n#", assertion_type="not_null")],
    )
    # No real newline introduces a bare `import os` statement.
    assert "\nimport os\n" not in hardened
    compile(hardened, "<hardened>", "exec")


def test_final_verify_catches_prohibited_token_in_raw_code():
    # The final re-verification still rejects prohibited tokens reaching the body.
    with pytest.raises(SecurityError):
        SecurityEnforcer.verify_and_inject("import os", [])


def test_numeric_range_bounds_are_interpolated():
    hardened = SecurityEnforcer.verify_and_inject(
        "x = 1",
        [MetricAssertion(column="revenue", assertion_type="range_bound", parameters={"min": 0, "max": 100})],
    )
    assert "df['revenue'].min() >= 0" in hardened
    assert "df['revenue'].max() <= 100" in hardened
    compile(hardened, "<hardened>", "exec")


def test_gateway_is_local_first_in_zero_spend():
    gateway = FailoverInferenceGateway(CostGuard())
    assert gateway.cloud_active is False
    raw, source = asyncio.run(gateway.generate_inference("p", "fallback prompt"))
    assert source == "local"
    plan = DeclarativeExecutionPlan.from_dict(__import__("json").loads(raw))
    assert "fallback prompt" in plan.pure_python_script


def test_local_isolated_executor_runs_code():
    out, ok = asyncio.run(
        DistributedExecutionMatrix.run_payload("print('hello-swarm')", is_online=False)
    )
    assert ok is True
    assert "hello-swarm" in out


def test_local_isolated_executor_reports_failure():
    out, ok = asyncio.run(
        DistributedExecutionMatrix.run_payload("raise ValueError('boom')", is_online=False)
    )
    assert ok is False
    assert "boom" in out


def test_parallel_swarm_local_fallback_succeeds():
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")
    results = orchestrator.run_swarm(
        ["summarize revenue", "detect anomalies"],
        schema_ctx="columns: revenue",
    )
    assert len(results) == 2
    assert all(r["status"] == "success" for r in results)
    assert all("Local deterministic verification" in r["telemetry"] for r in results)


def test_swarm_rejects_unsafe_generated_plan(monkeypatch):
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")

    async def _malicious(prompt, fallback_prompt):
        return (
            __import__("json").dumps(
                {
                    "analytical_rationale": "bad",
                    "pure_python_script": "import os\nos.listdir('/')",
                    "data_quality_assertions": [],
                }
            ),
            "cloud",
        )

    monkeypatch.setattr(orchestrator.gateway, "generate_inference", _malicious)
    result = asyncio.run(orchestrator.orchestrate_node_task("q", "ctx"))
    assert result["status"] == "rejected"


def test_parse_plan_strips_markdown_code_fences():
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")
    fenced = (
        "```json\n"
        '{"analytical_rationale": "fenced", '
        '"pure_python_script": "print(1)", '
        '"data_quality_assertions": []}\n'
        "```"
    )
    plan = orchestrator._parse_plan(fenced)
    assert plan.analytical_rationale == "fenced"
    assert plan.pure_python_script == "print(1)"


def test_parse_plan_handles_non_dict_json_gracefully():
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")
    # Valid JSON that is not an object: json.loads succeeds but from_dict would
    # raise AttributeError. Must fall back to the deterministic stub, not crash.
    for payload in ("[1, 2, 3]", '"a bare string"', "null", "42", "true"):
        plan = orchestrator._parse_plan(payload)
        assert plan.analytical_rationale == "Fallback structural extraction"


def test_local_fallback_query_with_prohibited_keyword_not_rejected():
    # A benign analytical query that merely *mentions* a prohibited word must not
    # be rejected: the local deterministic plan embeds it only as a repr-escaped
    # string literal and is trusted, so the untrusted-code scanner is skipped.
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")
    for query in (
        "Analyze subprocess throughput metrics",
        "Evaluate socket latency and eval the open positions",
    ):
        result = asyncio.run(orchestrator.orchestrate_node_task(query, "columns: x"))
        assert result["status"] == "success", result
        assert "Local deterministic verification" in result["telemetry"]


def test_cloud_plan_with_prohibited_keyword_still_rejected(monkeypatch):
    # Defense-in-depth: untrusted cloud output is still fully scanned.
    orchestrator = AutonomousSwarmOrchestrator(session_id="test")

    async def _cloud(prompt, fallback_prompt):
        return (
            __import__("json").dumps(
                {
                    "analytical_rationale": "bad",
                    "pure_python_script": "import subprocess\nsubprocess.run('x')",
                    "data_quality_assertions": [],
                }
            ),
            "cloud",
        )

    monkeypatch.setattr(orchestrator.gateway, "generate_inference", _cloud)
    result = asyncio.run(orchestrator.orchestrate_node_task("q", "ctx"))
    assert result["status"] == "rejected"


def test_concurrent_mixed_sources_keep_trust_isolated(monkeypatch):
    # Regression for the race condition: a single gateway is shared across all
    # parallel workers. A trusted local task (whose query mentions a prohibited
    # word) and an untrusted cloud task with a prohibited signature run together;
    # the local task must NOT be scanned/rejected and the cloud task MUST be.
    import json as _json

    orchestrator = AutonomousSwarmOrchestrator(session_id="test")

    async def _mixed(prompt, fallback_prompt):
        if "subprocess" in fallback_prompt:
            await asyncio.sleep(0.02)  # yield so a cloud task can interleave
            script = (
                f"objective = {fallback_prompt!r}\n"
                "print('Local deterministic verification:', objective[:200])\n"
            )
            return (
                _json.dumps(
                    {
                        "analytical_rationale": "local-task",
                        "pure_python_script": script,
                        "data_quality_assertions": [],
                    }
                ),
                "local",
            )
        return (
            _json.dumps(
                {
                    "analytical_rationale": "cloud-task",
                    "pure_python_script": "import socket\nsocket.socket()",
                    "data_quality_assertions": [],
                }
            ),
            "cloud",
        )

    monkeypatch.setattr(orchestrator.gateway, "generate_inference", _mixed)
    results = orchestrator.run_swarm(
        ["Analyze subprocess throughput metrics", "do the cloud aggregation"],
        schema_ctx="columns: x",
    )
    by = {r["rationale"]: r for r in results}
    assert by["local-task"]["status"] == "success", by["local-task"]
    assert by["cloud-task"]["status"] == "rejected", by["cloud-task"]
