from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .approval_gate import ApprovalGate, ApprovalRequired
from .audit_log import AuditLog
from .complexity_scorer import ComplexityScorer
from .cost_guard import CostGuard, CostGuardError
from .local_model_router import LocalModelRouter
from .memory_commit import MemoryCommit
from .minifier import ManifestMinifier
from .vector_cache import VectorCache
from .verifier import Verifier


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    route_tier: str
    output: str
    cached: bool
    details: Dict[str, Any]


class SovereignAutomationCore:
    """
    Local-first, no-spend EAOS execution primitive.

    This is not a paid API wrapper. It is a guarded execution router that:
    - compresses VHLL/declarative intent,
    - checks local verified memory first,
    - scores complexity,
    - routes simple work locally,
    - queues high-risk work for approval,
    - blocks paid/cloud escalation by default,
    - logs everything.
    """

    def __init__(self) -> None:
        self.audit = AuditLog()
        self.cost_guard = CostGuard()
        self.approval_gate = ApprovalGate()
        self.minifier = ManifestMinifier()
        self.cache = VectorCache()
        self.scorer = ComplexityScorer()
        self.router = LocalModelRouter()
        self.verifier = Verifier()
        self.memory = MemoryCommit(self.cache, self.verifier)

    def execute(
        self,
        system_declaration: str,
        dynamic_context: str,
        objective: str,
        embedding_vector: List[float],
        namespace: str = "default",
        actor: str = "sovereign-core",
    ) -> ExecutionResult:
        correlation_id = hashlib.sha256(f"{objective}|{namespace}".encode("utf-8")).hexdigest()[:16]
        self.audit.info(actor, "execution_received", {"namespace": namespace, "objective": objective[:250]}, correlation_id)

        clean_system, clean_context = self.minifier.minify(system_declaration, dynamic_context)
        self.audit.info(actor, "manifest_minified", {"system_chars": len(clean_system), "context_chars": len(clean_context)}, correlation_id)

        cache_hit = self.cache.search(embedding_vector, namespace=namespace)
        if cache_hit:
            self.audit.info(actor, "vector_cache_hit", {"record_id": cache_hit.record_id, "confidence": cache_hit.confidence}, correlation_id)
            return ExecutionResult(
                status="ok",
                route_tier="VERIFIED_VECTOR_CACHE",
                output=cache_hit.output,
                cached=True,
                details={"confidence": cache_hit.confidence, "record_id": cache_hit.record_id},
            )

        complexity = self.scorer.score(objective=objective, context=clean_context)
        route = self.router.route(complexity.score)

        try:
            self.cost_guard.assert_allowed(route.decision)
        except CostGuardError as exc:
            self.audit.blocked(actor, "cost_guard_block", {"error": str(exc), "route": route.decision.__dict__}, correlation_id)
            raise

        self.audit.info(actor, "route_selected", {"route": route.decision.__dict__, "reason": route.reason, "complexity": complexity.__dict__}, correlation_id)

        if route.decision.tier == "HUMAN_REVIEW_QUEUE":
            try:
                self.approval_gate.require(
                    action="complex_or_external_execution",
                    reason=route.reason,
                    payload={
                        "objective": objective,
                        "complexity": complexity.__dict__,
                        "route": route.decision.__dict__,
                    },
                )
            except ApprovalRequired as exc:
                self.audit.blocked(actor, "approval_required", {"message": str(exc)}, correlation_id)
                return ExecutionResult(
                    status="approval_required",
                    route_tier="HUMAN_REVIEW_QUEUE",
                    output=str(exc),
                    cached=False,
                    details={"complexity": complexity.__dict__, "reason": route.reason},
                )

        if route.decision.tier == "DETERMINISTIC_LOCAL":
            output = self._deterministic_execute(clean_system, clean_context, objective)
        elif route.decision.tier == "LOCAL_MODEL":
            output = self._local_model_placeholder(clean_system, clean_context, objective)
        else:
            output = "Execution queued. No unsafe route executed."

        verified = self.verifier.verify_text_output(output)
        if not verified.passed:
            self.audit.blocked(actor, "verification_failed", {"reason": verified.reason}, correlation_id)
            return ExecutionResult("blocked", route.decision.tier, verified.reason, False, {"verification": verified.__dict__})

        record_id = self.memory.commit_verified(embedding_vector, output, namespace=namespace)
        self.audit.info(actor, "execution_committed", {"record_id": record_id, "route_tier": route.decision.tier}, correlation_id)
        return ExecutionResult(
            status="ok",
            route_tier=route.decision.tier,
            output=output,
            cached=False,
            details={"record_id": record_id, "complexity": complexity.__dict__},
        )

    def _deterministic_execute(self, clean_system: str, clean_context: str, objective: str) -> str:
        return (
            "DETERMINISTIC_LOCAL_RESULT\n"
            f"Objective: {objective}\n"
            f"System chars: {len(clean_system)}\n"
            f"Context chars: {len(clean_context)}\n"
            "Status: draft_created_no_external_execution"
        )

    def _local_model_placeholder(self, clean_system: str, clean_context: str, objective: str) -> str:
        # Placeholder is intentionally safe: production implementation must call a local-only model adapter.
        return (
            "LOCAL_MODEL_ROUTE_SELECTED\n"
            f"Objective: {objective}\n"
            "Status: local_model_adapter_required"
        )


if __name__ == "__main__":
    dim = int(os.getenv("GMAOS_EMBEDDING_DIM", "384"))
    core = SovereignAutomationCore()
    result = core.execute(
        system_declaration="""You are a no-spend local execution fabric.""",
        dynamic_context="""Create a safe draft and do not call paid services.""",
        objective="Create a local-only project status draft.",
        embedding_vector=[0.001] * dim,
        namespace="smoke-test",
    )
    print(result)
