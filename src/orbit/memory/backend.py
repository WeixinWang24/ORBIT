"""Retrieval backend interface for ORBIT memory search.

This module defines the execution seam between the current application-side
retrieval implementation and a future PostgreSQL/pgvector-backed backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orbit.memory.retrieval import RetrievalScore
from orbit.memory.weights import MemoryRetrievalWeights, default_memory_retrieval_weights
from orbit.models import MemoryEmbedding, MemoryRecord


class MemoryRetrievalBackend(ABC):
    """Abstract retrieval backend for memory scoring."""

    @abstractmethod
    def score(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        records: list[MemoryRecord],
        embeddings: dict[str, MemoryEmbedding],
        weights: MemoryRetrievalWeights | None = None,
    ) -> list[RetrievalScore]:
        """Return scored memory candidates in backend-specific order."""


class PostgresMemoryRetrievalBackend(MemoryRetrievalBackend):
    """Reserved PostgreSQL/pgvector retrieval backend stub for later phases."""

    backend_name = "postgres"
    strategy_name = "pgvector_reserved_stub"

    def score(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        records: list[MemoryRecord],
        embeddings: dict[str, MemoryEmbedding],
        weights: MemoryRetrievalWeights | None = None,
    ) -> list[RetrievalScore]:
        return []


class ApplicationMemoryRetrievalBackend(MemoryRetrievalBackend):
    """Current app-side hybrid retrieval backend."""

    backend_name = "application"
    strategy_name = "hybrid_embedding_lexical_v1"

    def score(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        records: list[MemoryRecord],
        embeddings: dict[str, MemoryEmbedding],
        weights: MemoryRetrievalWeights | None = None,
    ) -> list[RetrievalScore]:
        from orbit.memory.memory_service import _tokenize
        from orbit.memory.embedding_service import cosine_similarity

        weights = weights or default_memory_retrieval_weights()
        query_tokens = _tokenize(query_text)
        scored: list[RetrievalScore] = []
        for record in records:
            embedding = embeddings.get(record.memory_id)
            if embedding is None:
                continue
            semantic_score = cosine_similarity(query_vector, embedding.vector)
            lexical_tokens = _tokenize(record.summary_text + "\n" + record.detail_text + "\n" + " ".join(record.tags))
            lexical_score = (len(query_tokens & lexical_tokens) / len(query_tokens)) if query_tokens else 0.0
            scope_boost = weights.durable_boost if str(record.scope) == "durable" else weights.session_boost
            salience_bonus = weights.salience_weight * float(getattr(record, "salience", 0.0) or 0.0)
            hybrid_score = (weights.semantic_weight * semantic_score) + (weights.lexical_weight * lexical_score) + scope_boost + salience_bonus
            if hybrid_score <= 0:
                continue
            scored.append(
                RetrievalScore(
                    memory=record,
                    hybrid_score=hybrid_score,
                    semantic_score=semantic_score,
                    lexical_score=lexical_score,
                )
            )
        scored.sort(key=lambda item: item.hybrid_score, reverse=True)
        return scored
