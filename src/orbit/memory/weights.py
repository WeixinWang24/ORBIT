"""Weighting configuration helpers for ORBIT memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from orbit.settings import (
    DEFAULT_MEMORY_RETRIEVAL_DURABLE_BOOST,
    DEFAULT_MEMORY_RETRIEVAL_LEXICAL_WEIGHT,
    DEFAULT_MEMORY_RETRIEVAL_SALIENCE_WEIGHT,
    DEFAULT_MEMORY_RETRIEVAL_SEMANTIC_WEIGHT,
    DEFAULT_MEMORY_RETRIEVAL_SESSION_BOOST,
)


@dataclass
class MemoryRetrievalWeights:
    semantic_weight: float = DEFAULT_MEMORY_RETRIEVAL_SEMANTIC_WEIGHT
    lexical_weight: float = DEFAULT_MEMORY_RETRIEVAL_LEXICAL_WEIGHT
    durable_boost: float = DEFAULT_MEMORY_RETRIEVAL_DURABLE_BOOST
    session_boost: float = DEFAULT_MEMORY_RETRIEVAL_SESSION_BOOST
    salience_weight: float = DEFAULT_MEMORY_RETRIEVAL_SALIENCE_WEIGHT


def default_memory_retrieval_weights() -> MemoryRetrievalWeights:
    return MemoryRetrievalWeights()
