"""Memory-domain models for ORBIT durable/session recall.

These models establish a bounded first slice for transcript-adjacent but
transcript-distinct memory persistence. They preserve the architecture rule
that visible transcript history, runtime metadata, durable memory, and vector
retrieval substrate are related but separate layers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from orbit.models.core import OrbitBaseModel, new_id


def utc_now() -> datetime:
    """Return the current UTC timestamp for memory records."""
    return datetime.now(timezone.utc)


class MemoryScope(str, Enum):
    """Represent whether a memory is session-scoped or cross-session durable."""

    SESSION = "session"
    DURABLE = "durable"


class MemoryType(str, Enum):
    """Represent the current first-slice semantic type for a memory record."""

    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    DECISION = "decision"
    TODO = "todo"
    LESSON = "lesson"
    SUMMARY = "summary"


class MemorySourceKind(str, Enum):
    """Represent the immediate source that produced a memory record."""

    TRANSCRIPT_MESSAGE = "transcript_message"
    CONTEXT_ARTIFACT = "context_artifact"
    MANUAL = "manual"
    DERIVED_SUMMARY = "derived_summary"


class MemoryRecord(OrbitBaseModel):
    """Represent one canonical memory record for ORBIT recall.

    The record itself is canonical truth. Any embedding/vector row derived from
    it is rebuildable derivative state rather than the primary durable object.
    """

    memory_id: str = Field(default_factory=lambda: new_id("memory"))
    scope: MemoryScope
    memory_type: MemoryType
    source_kind: MemorySourceKind
    session_id: str | None = None
    run_id: str | None = None
    source_message_id: str | None = None
    summary_text: str
    detail_text: str = ""
    tags: list[str] = Field(default_factory=list)
    salience: float = 0.5
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEmbedding(OrbitBaseModel):
    """Represent a derived embedding row for semantic memory retrieval."""

    embedding_id: str = Field(default_factory=lambda: new_id("membed"))
    memory_id: str
    model_name: str
    embedding_dim: int
    content_sha1: str
    vector: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
