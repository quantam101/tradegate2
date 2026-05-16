from __future__ import annotations

import hashlib
from typing import List

from .vector_cache import VectorCache
from .verifier import Verifier


class MemoryCommit:
    def __init__(self, cache: VectorCache, verifier: Verifier) -> None:
        self.cache = cache
        self.verifier = verifier

    def commit_verified(self, vector: List[float], output: str, namespace: str = "default") -> str:
        result = self.verifier.verify_text_output(output)
        if not result.passed:
            raise ValueError(f"Refusing to commit unverified output: {result.reason}")
        record_id = "intent_state:" + hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]
        self.cache.commit(record_id, vector, output, verified=True, namespace=namespace)
        return record_id
