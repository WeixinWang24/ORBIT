"""Adapter contracts for isolated ORBIT interface development."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import Field

from orbit.models.core import OrbitBaseModel


class InterfaceSession(OrbitBaseModel):
    session_id: str
    conversation_id: str
    backend_name: str
    model: str
    updated_at: datetime
    message_count: int = 0
    last_message_preview: str = ""
    status: str = "idle"


class InterfaceMessage(OrbitBaseModel):
    session_id: str
    role: str
    content: str
    turn_index: int
    created_at: datetime | None = None
    message_kind: str | None = None
    metadata: dict = Field(default_factory=dict)


class InterfaceEvent(OrbitBaseModel):
    session_id: str
    event_type: str
    timestamp: datetime
    payload: dict = Field(default_factory=dict)


class InterfaceArtifact(OrbitBaseModel):
    session_id: str
    artifact_type: str
    source: str
    content: str


class InterfaceToolCall(OrbitBaseModel):
    session_id: str
    tool_name: str
    status: str
    side_effect_class: str = "safe"
    requires_approval: bool = False
    summary: str = ""
    payload: dict = Field(default_factory=dict)


class InterfaceApproval(OrbitBaseModel):
    approval_request_id: str
    session_id: str
    tool_name: str
    side_effect_class: str = "safe"
    status: str = "pending"
    summary: str = ""
    opened_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


class OrbitInterfaceAdapter(Protocol):
    def list_sessions(self) -> list[InterfaceSession]: ...

    def get_session(self, session_id: str) -> InterfaceSession | None: ...

    def list_messages(self, session_id: str) -> list[InterfaceMessage]: ...

    def list_events(self, session_id: str) -> list[InterfaceEvent]: ...

    def list_artifacts(self, session_id: str) -> list[InterfaceArtifact]: ...

    def list_tool_calls(self, session_id: str) -> list[InterfaceToolCall]: ...

    def list_open_approvals(self) -> list[InterfaceApproval]: ...
