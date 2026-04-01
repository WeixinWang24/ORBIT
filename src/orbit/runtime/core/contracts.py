"""Execution contracts for ORBIT runtime coordination.

This module defines the descriptor objects that bridge planning/orchestration
and execution. The immediate goal is to make run setup explicit before the
runtime grows more complex.
"""

from __future__ import annotations

from pydantic import Field

from orbit.models.core import OrbitBaseModel, new_id


class WorkspaceDescriptor(OrbitBaseModel):
    """Describe the workspace boundary available to a run."""

    cwd: str
    writable_roots: list[str] = Field(default_factory=list)


class AgentDescriptor(OrbitBaseModel):
    """Describe the agent/runtime persona selected for a run."""

    profile_id: str = "orbit-default"
    mode: str = "dummy"
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None


class ModelDescriptor(OrbitBaseModel):
    """Describe the execution source backing the run.

    In the current phase this mainly captures whether the run is driven by a
    deterministic dummy scenario rather than a live provider.
    """

    provider: str = "dummy"
    model_id: str = "dummy-runtime"
    thinking_mode: str = "disabled"


class ExecutionDescriptor(OrbitBaseModel):
    """Describe run-level execution limits and queue behavior."""

    max_turns: int = 8
    timeout_ms: int = 30_000
    queue_policy: str = "interrupt"


class ToolingDescriptor(OrbitBaseModel):
    """Describe tool policy attached to the run."""

    toolset_id: str = "default"
    permission_profile_id: str = "governed-v0"
    allow_concurrency: bool = False


class DeliveryDescriptor(OrbitBaseModel):
    """Describe the initial delivery projection for a run."""

    surface: str = "notebook"
    reply_mode: str = "inline"


class ProvenanceDescriptor(OrbitBaseModel):
    """Describe where the run request came from."""

    source_event_id: str | None = None
    sender_id: str = "local-user"
    trust: str = "trusted"


class RunDescriptor(OrbitBaseModel):
    """Primary cross-layer execution contract for ORBIT runs.

    This descriptor is assembled before execution begins and passed into the
    runtime path as a single object. It is intentionally modest in v0 and can
    grow gradually as execution families and surfaces become more capable.
    """

    run_id: str = Field(default_factory=lambda: new_id("run"))
    session_key: str
    conversation_id: str
    runtime_family: str = "dummy"
    workspace: WorkspaceDescriptor
    agent: AgentDescriptor = Field(default_factory=AgentDescriptor)
    model: ModelDescriptor = Field(default_factory=ModelDescriptor)
    execution: ExecutionDescriptor = Field(default_factory=ExecutionDescriptor)
    tools: ToolingDescriptor = Field(default_factory=ToolingDescriptor)
    delivery: DeliveryDescriptor = Field(default_factory=DeliveryDescriptor)
    provenance: ProvenanceDescriptor = Field(default_factory=ProvenanceDescriptor)
    user_input: str
    dummy_scenario: str = "tool_then_finish"
