from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class CacheHit:
    output: str
    confidence: float
    record_id: str


class VectorCache:
    def __init__(self, path: str | None = None, embedding_dim: int | None = None, match_floor: float | None = None) -> None:
        self.path = Path(path or os.getenv("GMAOS_VECTOR_CACHE", "./data/vector_cache.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_dim = embedding_dim or int(os.getenv("GMAOS_EMBEDDING_DIM", "384"))
        self.match_floor = match_floor or float(os.getenv("GMAOS_SEMANTIC_MATCH_FLOOR", "0.96"))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS intent_cache (
                    id TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL,
                    execution_output TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    namespace TEXT NOT NULL DEFAULT 'default',
                    created_at REAL NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_intent_cache_namespace ON intent_cache(namespace)")

    def _validate(self, vector: List[float]) -> None:
        if not isinstance(vector, list):
            raise ValueError("Embedding must be a list of floats.")
        if len(vector) != self.embedding_dim:
            raise ValueError(f"Embedding dimension mismatch: expected={self.embedding_dim}, actual={len(vector)}")
        for value in vector:
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("Embedding contains non-numeric or non-finite value.")

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def search(self, vector: List[float], namespace: str = "default") -> Optional[CacheHit]:
        self._validate(vector)
        best: Optional[CacheHit] = None
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, vector_json, execution_output FROM intent_cache WHERE namespace = ? AND verified = 1",
                (namespace,),
            ).fetchall()
        for record_id, vector_json, output in rows:
            existing = json.loads(vector_json)
            confidence = self._cosine(vector, existing)
            if confidence >= self.match_floor and (best is None or confidence > best.confidence):
                best = CacheHit(output=output, confidence=confidence, record_id=record_id)
        return best

    def commit(self, record_id: str, vector: List[float], output: str, verified: bool = False, namespace: str = "default") -> None:
        self._validate(vector)
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO intent_cache (id, vector_json, execution_output, verified, namespace, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (record_id, json.dumps([float(x) for x in vector]), output, int(verified), namespace, time.time()),
            )
