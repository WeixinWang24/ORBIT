"""Weighting configuration helpers for ORBIT memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryRetrievalWeights:
    semantic_weight: float = 0.8
    lexical_weight: float = 0.2
    durable_boost: float = 0.05
    session_boost: float = 0.0
    salience_weight: float = 0.05


def default_memory_retrieval_weights() -> MemoryRetrievalWeights:
    return MemoryRetrievalWeights()
