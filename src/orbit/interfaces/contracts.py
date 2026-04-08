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
    runtime_mode: str = "dev"
    workspace_root: str = ""
    mode_policy_profile: str = "dev-default"
    self_runtime_visibility: str = "workspace_only"
    self_modification_posture: str = "not_enabled"
    updated_at: datetime
    message_count: int = 0
    last_message_preview: str = ""
    status: str = "idle"
    # self-change / build projection (first slice)
    active_self_change_plan_id: str | None = None
    active_build_record_id: str | None = None
    last_build_status: str | None = None
    last_build_summary: str | None = None
    build_policy_profile: str = "none"


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
