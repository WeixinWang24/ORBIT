from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from orbit.models import ConversationSession
from orbit.runtime.execution.contracts.plans import ExecutionPlan


@dataclass
class CapabilityAttachDecision:
    attach_allowed: bool
    reason: str
    source: str
    governance_mode: str | None = None


class CapabilityAttachPolicy(Protocol):
    def decide(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityAttachDecision:
        ...


class RuntimeCoreMinimalCapabilityPolicy:
    def decide(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityAttachDecision:
        if plan.tool_request is None:
            return CapabilityAttachDecision(
                attach_allowed=True,
                reason="no_tool_request",
                source="runtime_core_minimal_policy",
                governance_mode="detached",
            )
        return CapabilityAttachDecision(
            attach_allowed=False,
            reason="tooling_detached_on_runtime_core_minimal",
            source="runtime_core_minimal_policy",
            governance_mode="detached",
        )


class PermissiveCapabilityAttachPolicy:
    def decide(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityAttachDecision:
        return CapabilityAttachDecision(
            attach_allowed=True,
            reason="permissive_attach",
            source="permissive_capability_attach_policy",
            governance_mode="attached",
        )
