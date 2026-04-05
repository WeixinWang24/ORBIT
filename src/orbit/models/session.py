"""Session and conversation-message models for ORBIT.

These models define ORBIT's first provider-agnostic conversation/session layer.
They intentionally represent canonical internal transcript state rather than any
single provider's request or response payload format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from orbit.models.core import OrbitBaseModel, new_id



RuntimeMode = Literal["dev", "evo"]


def utc_now() -> datetime:
    """Return the current UTC timestamp for session/message records."""
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    """Represent the minimal lifecycle state of a conversation session."""

    ACTIVE = "active"
    COMPLETED = "completed"


class MessageRole(str, Enum):
    """Represent the canonical internal role of a conversation message.

    ORBIT keeps tool-result messages distinct from user-authored messages even
    when a provider-specific projection later has to flatten them into a more
    limited wire format.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class GovernedToolState(OrbitBaseModel):
    """Represent the minimal explicit governed-tool state for a session.

    This is intentionally lightweight in the current phase. It provides a more
    explicit runtime truth for approval/rejection/reissue handling without yet
    introducing a larger dedicated persistence subsystem.
    """

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        "waiting_for_approval": {"approved", "rejected"},
        "approved": {"executed"},
        "rejected": {"blocked_reissue"},
        "blocked_reissue": set(),
        "executed": set(),
    }

    governed_tool_state_id: str = Field(default_factory=lambda: new_id("gtool"))
    tool_name: str
    state: str
    approval_request_id: str | None = None
    side_effect_class: str = "safe"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    opened_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def can_transition_to(self, new_state: str) -> bool:
        """Return whether a transition is allowed from the current state."""
        if self.state == new_state:
            return True
        return new_state in self.ALLOWED_TRANSITIONS.get(self.state, set())

    def transition(self, new_state: str, *, note: str | None = None) -> "GovernedToolState":
        """Return a copied state with a validated next state.

        This keeps the first state-machine rule lightweight but explicit.
        """
        if not self.can_transition_to(new_state):
            raise ValueError(f"invalid governed tool state transition: {self.state} -> {new_state}")
        return self.model_copy(update={
            "state": new_state,
            "note": note if note is not None else self.note,
            "updated_at": utc_now(),
        })


class ConversationSession(OrbitBaseModel):
    """Represent a linear multi-turn conversation session in ORBIT.

    The session model remains intentionally small, but it may carry lightweight
    session-scoped control metadata such as a pending approval artifact for the
    first governed tool-calling path.
    """

    session_id: str = Field(default_factory=lambda: new_id("session"))
    conversation_id: str
    backend_name: str
    model: str
    runtime_mode: RuntimeMode = "dev"
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    governed_tool_state: GovernedToolState | None = None


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
