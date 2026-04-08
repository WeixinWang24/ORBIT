"""Backend-generic execution plan models for ORBIT runtime.

This module replaces the earlier dummy-specific result shape with a more neutral
execution-plan vocabulary. The goal is to let dummy and future live model
backends share the same coordinator-facing contract without pretending that all
execution sources are dummy engines.
"""

from __future__ import annotations

from pydantic import Field

from orbit.models.core import OrbitBaseModel


class ToolRequest(OrbitBaseModel):
    """Describe a bounded tool request emitted by an execution backend."""

    tool_name: str
    input_payload: dict = Field(default_factory=dict)
    requires_approval: bool = False
    side_effect_class: str = "safe"


class ExecutionPlan(OrbitBaseModel):
    """Describe the next bounded execution result emitted by a backend.

    The current plan model is intentionally small. It captures the minimum
    information needed by the coordinator to continue governed runtime flow
    while remaining backend-neutral.
    """

    source_backend: str
    plan_label: str
    final_text: str | None = None
    tool_request: ToolRequest | None = None
    should_finish_after_tool: bool = True
    failure_reason: str | None = None
    metadata: dict = Field(default_factory=dict)
