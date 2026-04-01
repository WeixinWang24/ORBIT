"""Session and conversation-message models for ORBIT.

These models define ORBIT's first provider-agnostic conversation/session layer.
They intentionally represent canonical internal transcript state rather than any
single provider's request or response payload format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from orbit.models.core import OrbitBaseModel, new_id



def utc_now() -> datetime:
    """Return the current UTC timestamp for session/message records."""
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    """Represent the minimal lifecycle state of a conversation session."""

    ACTIVE = "active"
    COMPLETED = "completed"


class MessageRole(str, Enum):
    """Represent the canonical internal role of a conversation message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ConversationSession(OrbitBaseModel):
    """Represent a linear multi-turn conversation session in ORBIT."""

    session_id: str = Field(default_factory=lambda: new_id("session"))
    conversation_id: str
    backend_name: str
    model: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ConversationMessage(OrbitBaseModel):
    """Represent one canonical transcript message inside a session."""

    message_id: str = Field(default_factory=lambda: new_id("msg"))
    session_id: str
    role: MessageRole
    content: str
    turn_index: int
    created_at: datetime = Field(default_factory=utc_now)
    provider_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
