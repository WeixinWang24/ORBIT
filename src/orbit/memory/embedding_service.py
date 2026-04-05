"""Local embedding service for ORBIT memory retrieval.

This first implementation intentionally stays simple:
- local sentence-transformers model
- sync embedding API suitable for current SessionManager path
- canonical memory rows remain in the store; embeddings remain derivative
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from orbit.models import MemoryEmbedding, MemoryRecord
from orbit.settings import DEFAULT_MEMORY_EMBEDDING_MODEL


@lru_cache(maxsize=2)
def _load_model(model_name: str) -> SentenceTransformer:
    """Load and cache the local embedding model."""
    return SentenceTransformer(model_name)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class EmbeddingService:
    """Embed memory text locally for ORBIT first-slice semantic retrieval."""

    def __init__(self, model_name: str = DEFAULT_MEMORY_EMBEDDING_MODEL):
        self.model_name = model_name

    @property
    def model(self) -> SentenceTransformer:
        return _load_model(self.model_name)

    def build_memory_text(self, record: MemoryRecord) -> str:
        """Build the canonical embedding text for one memory record."""
        parts = [record.summary_text.strip()]
        if record.detail_text.strip() and record.detail_text.strip() != record.summary_text.strip():
            parts.append(record.detail_text.strip())
        if record.tags:
            parts.append("tags: " + ", ".join(record.tags))
        return "\n\n".join(part for part in parts if part)

    def embed_text(self, text: str) -> list[float]:
        """Return one embedding vector for the given text."""
        vector = self.model.encode(text, normalize_embeddings=False)
        return [float(value) for value in vector.tolist()]

    def embed_memory_record(self, record: MemoryRecord) -> MemoryEmbedding:
        """Create a derived embedding row for one memory record."""
        text = self.build_memory_text(record)
        vector = self.embed_text(text)
        return MemoryEmbedding(
            memory_id=record.memory_id,
            model_name=self.model_name,
            embedding_dim=len(vector),
            content_sha1=hashlib.sha1(text.encode("utf-8")).hexdigest(),
            vector=vector,
            metadata={
                "scope": str(record.scope),
                "memory_type": str(record.memory_type),
            },
        )
