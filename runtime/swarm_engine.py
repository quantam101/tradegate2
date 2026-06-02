"""
Declarative VHLL Multi-Agent Swarm Engine (Python Runtime)

A local-first, fault-tolerant orchestration layer that compiles declarative
analytical intent (VHLL) into hardened, sandboxed execution plans and runs them
across a parallel worker swarm.

Design goals (consistent with the rest of the GMAOS/EAOS runtime):
- Local-first / zero-spend by default. Cloud inference (e.g. Gemini) is only
  attempted when paid adapters are explicitly enabled via ``CostGuard``; any
  cloud failure (quota, blackout, timeout) fails over to local deterministic
  inference without dropping the session.
- Static security guardrails over generated code before it is ever executed.
- Isolated execution: each worker runs its payload in its own temp directory
  with a unique scratch file, so parallel workers never clobber one another.
- Structured telemetry + audit, matching ``sovereign_core``.

This module intentionally uses stdlib dataclasses (not pydantic) to match the
existing runtime and avoid pulling in extra dependencies. ``google.genai`` and
``e2b_code_interpreter`` are optional and imported lazily; their absence simply
forces the local execution paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .audit_log import AuditLog
from .cost_guard import CostGuard, CostGuardError, RouteDecision
from .telemetry import TelemetryCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] SYSTEM_LAYER: %(message)s",
)
logger = logging.getLogger("EnterpriseQuantAgent")


class SecurityError(RuntimeError):
    """Raised when generated code violates the static security policy."""


# ==========================================
# 1. STRUCTURAL META-SCHEMAS (VHLL DECLARATIVE LAYER)
# ==========================================

_ASSERTION_TYPES = ("not_null", "range_bound", "type_invariance")


@dataclass(frozen=True)
class MetricAssertion:
    column: str
    assertion_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.assertion_type not in _ASSERTION_TYPES:
            raise ValueError(
                f"Unsupported assertion_type '{self.assertion_type}'. "
                f"Expected one of {_ASSERTION_TYPES}."
            )

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MetricAssertion":
        return MetricAssertion(
            column=str(data["column"]),
            assertion_type=str(data["assertion_type"]),
            parameters=dict(data.get("parameters") or {}),
        )


@dataclass(frozen=True)
class DeclarativeExecutionPlan:
    """Strict, declarative compilation target separating intent from execution."""

    analytical_rationale: str
    pure_python_script: str
    required_packages: List[str] = field(default_factory=list)
    data_quality_assertions: List[MetricAssertion] = field(default_factory=list)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "DeclarativeExecutionPlan":
        assertions = [
            MetricAssertion.from_dict(item)
            for item in (data.get("data_quality_assertions") or [])
        ]
        return DeclarativeExecutionPlan(
            analytical_rationale=str(data.get("analytical_rationale", "")),
            pure_python_script=str(data.get("pure_python_script", "")),
            required_packages=list(data.get("required_packages") or []),
            data_quality_assertions=assertions,
        )


# ==========================================
# 2. STATIC SECURITY GUARDRAIL & ASSERTION INJECTION
# ==========================================

class SecurityEnforcer:
    """Static analysis guardrail applied to generated code before execution."""

    PROHIBITED_SIGNATURES = [
        r"\bimport\s+os\b",
        r"\bimport\s+sys\b",
        r"\bfrom\s+os\b",
        r"\bfrom\s+sys\b",
        r"\bsubprocess\b",
        r"\bshutil\b",
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bsocket\b",
        r"\bpty\b",
        r"\bgetattr\s*\(",
        r"\bsetattr\s*\(",
        r"\bopen\s*\(",
    ]

    _FENCE_RE = re.compile(r"```(?:python)?\s*|\s*```")

    @classmethod
    def verify(cls, raw_code: str) -> str:
        """Strip code fences and reject any prohibited signature."""
        clean_code = cls._FENCE_RE.sub("", raw_code).strip()
        for pattern in cls.PROHIBITED_SIGNATURES:
            if re.search(pattern, clean_code):
                raise SecurityError(
                    f"Operational policy infraction: unauthorized signature "
                    f"'{pattern}' rejected."
                )
        return clean_code

    @staticmethod
    def _numeric_literal(value: Any, default: str) -> str:
        """Return a safe numeric code literal, rejecting non-numeric input.

        Bounds are interpolated into generated code as expressions, so anything
        that is not a plain int/float is a code-injection vector and is rejected.
        ``bool`` is excluded explicitly (it subclasses ``int``).
        """
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SecurityError(
                f"Non-numeric assertion bound rejected: {value!r}"
            )
        return repr(value)

    @classmethod
    def build_assertion_block(cls, assertions: List[MetricAssertion]) -> str:
        if not assertions:
            return ""
        block = "\n# --- AUTOMATED INVARIANT ASSERTIONS ---\n"
        for asm in assertions:
            col = asm.column  # interpolated only via !r (safe string literal)
            if asm.assertion_type == "not_null":
                msg = f"Violation: Null found in {col}"
                block += (
                    f"assert df[{col!r}].isnull().sum() == 0, {msg!r}\n"
                )
            elif asm.assertion_type == "range_bound":
                min_v = cls._numeric_literal(asm.parameters.get("min"), "float('-inf')")
                max_v = cls._numeric_literal(asm.parameters.get("max"), "float('inf')")
                msg = f"Violation: Range bounds broken in {col}"
                block += (
                    f"assert df[{col!r}].min() >= {min_v} and "
                    f"df[{col!r}].max() <= {max_v}, {msg!r}\n"
                )
            elif asm.assertion_type == "type_invariance":
                expected = str(asm.parameters.get("dtype", "object"))
                msg = f"Violation: dtype invariance broken in {col}"
                block += (
                    f"assert str(df[{col!r}].dtype) == {expected!r}, {msg!r}\n"
                )
        return block

    @classmethod
    def verify_and_inject(
        cls,
        raw_code: str,
        assertions: List[MetricAssertion],
        preamble: bool = True,
    ) -> str:
        """Validate code and append declarative invariant assertions.

        Defense-in-depth: each interpolated value is sanitized in
        ``build_assertion_block`` (numeric bounds validated, all strings via
        ``repr``), and the fully assembled program is re-verified so any
        prohibited signature that slips into the assertion block is still caught.
        """
        clean_code = cls.verify(raw_code)
        assertion_block = cls.build_assertion_block(assertions)
        header = "import pandas as pd\nimport numpy as np\n" if preamble else ""
        combined = header + clean_code + assertion_block
        cls.verify(combined)
        return combined


# ==========================================
# 3. FAILOVER INFERENCE GATEWAY
# ==========================================

class FailoverInferenceGateway:
    """
    Routes inference between cloud infrastructure and a local deterministic
    fallback. Cloud is gated by ``CostGuard``: in strict zero-spend mode the
    gateway never touches a paid endpoint and serves deterministic local plans.
    """

    def __init__(self, cost_guard: CostGuard | None = None) -> None:
        self.cost_guard = cost_guard or CostGuard()
        self.cloud_model = os.getenv("GMAOS_CLOUD_MODEL", "gemini-2.5-pro")
        self.client: Any = None
        self.cloud_active = self._init_cloud()

    def _init_cloud(self) -> bool:
        """Enable cloud only if the CostGuard allows a paid route AND deps exist."""
        try:
            self.cost_guard.assert_allowed(
                RouteDecision(
                    tier="EXTERNAL_PAID_LLM",
                    endpoint=self.cloud_model,
                    estimated_cost_usd=0.0,
                    action="cloud_inference",
                    paid=True,
                )
            )
        except CostGuardError as exc:
            logger.info("Cloud inference disabled by cost guard (%s). Local-first mode.", exc)
            return False

        try:
            from google import genai  # type: ignore import-not-found

            self.client = genai.Client()
            return True
        except Exception:  # pragma: no cover - depends on optional dep + creds
            logger.warning("Cloud core engine unreachable. Initializing local routing.")
            return False

    async def generate_inference(self, prompt: str, fallback_prompt: str) -> str:
        if self.cloud_active and self.client is not None:
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.cloud_model,
                    contents=prompt,
                )
                text = getattr(response, "text", None)
                if text:
                    return text
                logger.warning("Cloud inference returned empty payload. Failing over to local.")
            except Exception as exc:  # pragma: no cover - network/credential dependent
                logger.error("Cloud channel severed (%s). Switching to local failover.", exc)
                self.cloud_active = False

        logger.info("Executing via local edge inference engine (air-gapped mode).")
        return await self._execute_local_inference(fallback_prompt)

    async def _execute_local_inference(self, prompt: str) -> str:
        """Deterministic local plan used when the cloud channel is unavailable.

        The generated script is self-contained (no undefined references) so it
        runs cleanly inside the isolated local subprocess.
        """
        script = (
            f"objective = {prompt!r}\n"
            "print('Local deterministic verification:', objective[:200])\n"
        )
        fallback = {
            "analytical_rationale": "Local deterministic fallback (transport disconnect or zero-spend).",
            "required_packages": [],
            "pure_python_script": script,
            "data_quality_assertions": [],
        }
        return json.dumps(fallback)


# ==========================================
# 4. DISTRIBUTED EXECUTION MATRIX (CLOUD <-> LOCAL ISOLATED)
# ==========================================

class DistributedExecutionMatrix:
    """Chooses a cloud sandbox when online, else an isolated local subprocess."""

    LOCAL_TIMEOUT_SECONDS = float(os.getenv("GMAOS_LOCAL_EXEC_TIMEOUT", "15"))

    @classmethod
    async def run_payload(cls, code: str, is_online: bool) -> Tuple[str, bool]:
        if is_online:
            try:
                from e2b_code_interpreter import AsyncSandbox  # type: ignore import-not-found

                async with AsyncSandbox() as sandbox:
                    execution = await sandbox.run_code(code)
                    if execution.error:
                        return f"Runtime Error: {execution.error.value}", False
                    return execution.logs.stdout, True
            except Exception as exc:  # pragma: no cover - optional dep + network
                logger.warning("Cloud container pool unavailable (%s). Routing locally.", exc)

        return await cls._run_local_isolated_subprocess(code)

    @classmethod
    async def _run_local_isolated_subprocess(cls, code: str) -> Tuple[str, bool]:
        """Run generated logic in a unique temp dir so parallel workers cannot collide."""
        with tempfile.TemporaryDirectory(prefix="gmaos_swarm_") as workdir:
            scratchpad = Path(workdir) / "agent_scratchpad.py"
            scratchpad.write_text(code, encoding="utf-8")

            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(scratchpad),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=cls.LOCAL_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return "Local Sandbox Exception: Execution Timed Out.", False

            if process.returncode != 0:
                return f"Local Sandbox Error:\n{stderr.decode(errors='replace')}", False
            return stdout.decode(errors="replace"), True


# ==========================================
# 5. AUTONOMOUS SWARM ORCHESTRATOR
# ==========================================

class AutonomousSwarmOrchestrator:
    """Distributes declarative analytical tasks across parallel worker nodes."""

    def __init__(self, session_id: str, cost_guard: CostGuard | None = None) -> None:
        self.session_id = session_id
        self.cost_guard = cost_guard or CostGuard()
        self.gateway = FailoverInferenceGateway(self.cost_guard)
        self.telemetry = TelemetryCollector("swarm-orchestrator")
        # AuditLog gained an optional telemetry hook later; stay compatible with
        # runtimes whose AuditLog predates it.
        try:
            self.audit = AuditLog(telemetry=self.telemetry)
        except TypeError:
            self.audit = AuditLog()

    def _parse_plan(self, raw_inference: str) -> DeclarativeExecutionPlan:
        try:
            return DeclarativeExecutionPlan.from_dict(json.loads(raw_inference))
        except (ValueError, KeyError, TypeError):
            return DeclarativeExecutionPlan(
                analytical_rationale="Fallback structural extraction",
                pure_python_script="print('Fallback processing anomaly verification.')",
            )

    async def orchestrate_node_task(self, sub_query: str, schema_ctx: str) -> Dict[str, Any]:
        """Process a single isolated segment of work end to end."""
        span = self.telemetry.span("orchestrate_node_task")
        self.telemetry.info(span, "worker_assigned", {"sub_query": sub_query[:200]})
        logger.info("Worker node assigned task: %s", sub_query)

        prompt = (
            "Deconstruct this data prompt into a DeclarativeExecutionPlan JSON "
            f"schema: {sub_query}. Schema: {schema_ctx}"
        )
        raw_inference = await self.gateway.generate_inference(prompt, fallback_prompt=sub_query)
        plan = self._parse_plan(raw_inference)

        try:
            hardened_code = SecurityEnforcer.verify_and_inject(
                plan.pure_python_script,
                plan.data_quality_assertions,
                preamble=bool(plan.data_quality_assertions),
            )
        except SecurityError as exc:
            self.telemetry.error(span, "security_rejected", {"error": str(exc)})
            self.audit.blocked("swarm-orchestrator", "security_rejected", {"error": str(exc), "sub_query": sub_query[:200]})
            return {"status": "rejected", "error": str(exc), "rationale": plan.analytical_rationale}

        telemetry, success = await DistributedExecutionMatrix.run_payload(
            hardened_code, is_online=self.gateway.cloud_active
        )

        status = "success" if success else "failed"
        self.telemetry.info(span, "node_complete", {"status": status})
        self.audit.info("swarm-orchestrator", "node_complete", {"status": status, "sub_query": sub_query[:200]})
        return {"status": status, "telemetry": telemetry, "rationale": plan.analytical_rationale}

    async def execute_parallel_swarm(
        self, batch_queries: List[str], schema_ctx: str
    ) -> List[Dict[str, Any]]:
        """Run analytical tasks concurrently across independent worker nodes."""
        tasks = [self.orchestrate_node_task(query, schema_ctx) for query in batch_queries]
        return await asyncio.gather(*tasks)

    def run_swarm(self, batch_queries: List[str], schema_ctx: str) -> List[Dict[str, Any]]:
        """Synchronous convenience wrapper around :meth:`execute_parallel_swarm`."""
        return asyncio.run(self.execute_parallel_swarm(batch_queries, schema_ctx))


if __name__ == "__main__":
    orchestrator = AutonomousSwarmOrchestrator(session_id="smoke-test")
    results = orchestrator.run_swarm(
        batch_queries=[
            "Summarize total revenue by region.",
            "Detect anomalies in daily order counts.",
        ],
        schema_ctx="columns: region, revenue, orders, date",
    )
    print(json.dumps(results, indent=2))
    print(f"\nTelemetry events: {len(orchestrator.telemetry.drain())}")
