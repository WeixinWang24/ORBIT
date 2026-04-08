"""Provider normalization boundary for ORBIT execution backends.

This module defines the coordinator-facing normalization contract that future
live model backends should target. It does not implement concrete provider
logic yet; instead, it reserves a narrow place where provider-specific outputs
can be adapted into ORBIT's backend-generic execution result shape.
"""

from __future__ import annotations

from pydantic import Field

from orbit.models.core import OrbitBaseModel
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest


class ProviderFailure(OrbitBaseModel):
    """Describe a normalized provider-side failure condition."""

    kind: str
    message: str
    raw_code: str | None = None
    retriable: bool = False


class ProviderNormalizedResult(OrbitBaseModel):
    """Describe normalized provider output before coordinator consumption.

    This object mirrors the current execution-plan-oriented runtime contract
    while leaving room for provider-side diagnostics to be represented in a
    structured form before final conversion into `ExecutionPlan`.
    """

    source_backend: str
    plan_label: str
    final_text: str | None = None
    tool_request: ToolRequest | None = None
    should_finish_after_tool: bool = True
    failure: ProviderFailure | None = None
    metadata: dict = Field(default_factory=dict)



def normalized_result_to_execution_plan(result: ProviderNormalizedResult) -> ExecutionPlan:
    """Convert a provider-normalized result into the coordinator-facing plan.

    This helper is intentionally small. Its role is to make the final handoff
    into ORBIT's generic execution plan explicit, rather than implicit inside a
    future backend implementation.
    """
    return ExecutionPlan(
        source_backend=result.source_backend,
        plan_label=result.plan_label,
        final_text=result.final_text,
        tool_request=result.tool_request,
        should_finish_after_tool=result.should_finish_after_tool,
        failure_reason=result.failure.message if result.failure else None,
        metadata=result.metadata or {},
    )
