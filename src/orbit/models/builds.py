"""Build and self-change plan models for ORBIT evo/dev mode lifecycle.

First-slice models for:
- SelfChangePlan: tracks a bounded self-modification intent in evo mode
- BuildRecord: tracks validation/verdict for a change that produced a runtime state transition

These are intentionally minimal. Persistence is via session.metadata, ContextArtifact,
and ExecutionEvent — no store/schema additions in this slice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from orbit.models.core import OrbitBaseModel


SelfChangePlanStatus = Literal[
    "planned",
    "approved",
    "active",
    "blocked",
    "completed",
    "abandoned",
    "superseded",
]

BuildRecordStatus = Literal[
    "planned",
    "validating",
    "passed",
    "failed",
    "blocked",
    "rolled_back",
]


def _new_plan_id() -> str:
    return f"scp_{uuid4().hex[:12]}"


def _new_build_id() -> str:
    return f"bld_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SelfChangePlan(OrbitBaseModel):
    """Represent a bounded self-modification plan in evo mode.

    A plan must be approved before execution and tracks its own lifecycle
    independently from a build validation record.
    """

    plan_id: str = Field(default_factory=_new_plan_id)
    session_id: str
    title: str
    description: str
    status: SelfChangePlanStatus = "planned"
    linked_build_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_status(self, status: SelfChangePlanStatus) -> "SelfChangePlan":
        return self.model_copy(update={"status": status, "updated_at": _utc_now()})

    def with_linked_build(self, build_id: str) -> "SelfChangePlan":
        return self.model_copy(update={"linked_build_id": build_id, "updated_at": _utc_now()})


class ValidationStep(OrbitBaseModel):
    """One step in a build validation sequence."""

    step_name: str
    status: Literal["pending", "passed", "failed", "skipped"] = "pending"
    output: str = ""
    recorded_at: datetime = Field(default_factory=_utc_now)


class BuildRecord(OrbitBaseModel):
    """Track the validation lifecycle for a single bounded self-change.

    A BuildRecord represents a validation/verdict cycle — not just a shell build.
    It may reference the SelfChangePlan that triggered it.
    """

    build_id: str = Field(default_factory=_new_build_id)
    session_id: str
    linked_plan_id: str | None = None
    status: BuildRecordStatus = "planned"
    summary: str = ""
    validation_steps: list[ValidationStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    finalized_at: datetime | None = None
    rolled_back_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_status(self, status: BuildRecordStatus) -> "BuildRecord":
        return self.model_copy(update={"status": status, "updated_at": _utc_now()})

    def with_validation_step(self, step: ValidationStep) -> "BuildRecord":
        return self.model_copy(update={
            "validation_steps": [*self.validation_steps, step],
            "updated_at": _utc_now(),
        })
