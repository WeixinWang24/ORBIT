"""Memory retrieval helpers and backend-prep structures for ORBIT.

This module keeps retrieval logic application-side for now, while creating a
clear adapter seam for later PostgreSQL/pgvector-backed execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from orbit.models import MemoryRecord


@dataclass
class RetrievalScore:
    memory: MemoryRecord
    hybrid_score: float
    semantic_score: float
    lexical_score: float
    durable_boost: float = 0.0
    session_boost: float = 0.0
    salience_bonus: float = 0.0


@dataclass
class RetrievalBackendPlan:
    backend: str
    strategy: str
    notes: str
    capabilities: dict | None = None


def default_retrieval_backend_plan() -> RetrievalBackendPlan:
    """Return the current retrieval execution posture.

    Current phase:
    - canonical persistence may be PostgreSQL-first
    - retrieval execution remains app-side
    - server-side vector execution is intentionally deferred
    """
    return RetrievalBackendPlan(
        backend="application",
        strategy="hybrid_embedding_lexical_v1",
        notes="App-side scoring today; explicit adapter seam reserved for future PostgreSQL/pgvector execution.",
        capabilities=None,
    )
