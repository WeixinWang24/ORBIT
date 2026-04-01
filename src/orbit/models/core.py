from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import (
    ApprovalDecisionType,
    ApprovalRequestStatus,
    RunStatus,
    StepStatus,
    StepType,
    TaskStatus,
    ToolInvocationStatus,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class OrbitBaseModel(BaseModel):
    model_config = {"use_enum_values": True}


class Task(OrbitBaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    title: str
    description: str
    status: TaskStatus = TaskStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    tags: list[str] = Field(default_factory=list)


class Run(OrbitBaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    task_id: str
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    current_step_id: str | None = None
    result_summary: str | None = None
    failure_reason: str | None = None


class RunStep(OrbitBaseModel):
    step_id: str = Field(default_factory=lambda: new_id("step"))
    run_id: str
    step_type: StepType
    status: StepStatus = StepStatus.PENDING
    index: int
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExecutionEvent(OrbitBaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    run_id: str
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    step_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    severity: str | None = None


class ToolInvocation(OrbitBaseModel):
    tool_invocation_id: str = Field(default_factory=lambda: new_id("tool"))
    run_id: str
    step_id: str
    tool_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    status: ToolInvocationStatus = ToolInvocationStatus.REQUESTED
    requested_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    side_effect_class: str = "safe"


class ApprovalRequest(OrbitBaseModel):
    approval_request_id: str = Field(default_factory=lambda: new_id("approval"))
    run_id: str
    step_id: str
    target_type: str
    target_id: str
    reason: str
    risk_level: str
    status: ApprovalRequestStatus = ApprovalRequestStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalDecision(OrbitBaseModel):
    approval_decision_id: str = Field(default_factory=lambda: new_id("decision"))
    approval_request_id: str
    decision: ApprovalDecisionType
    decided_at: datetime = Field(default_factory=utc_now)
    decided_by: str = "human"
    note: str | None = None


class ContextArtifact(OrbitBaseModel):
    context_artifact_id: str = Field(default_factory=lambda: new_id("ctx"))
    run_id: str
    artifact_type: str
    content: str
    source: str
    created_at: datetime = Field(default_factory=utc_now)
