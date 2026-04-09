from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from orbit.models import ConversationSession
from orbit.runtime.execution.contracts.plans import ExecutionPlan
from orbit.runtime.governance.tool_approval_policy import PolicyEvaluationInput, evaluate_tool_approval_policy
from orbit.runtime.mcp.governance import filesystem_server_allowed_root, resolve_filesystem_mcp_target_path


@dataclass
class CapabilityAttachDecision:
    attach_allowed: bool
    reason: str
    source: str
    governance_mode: str | None = None


@dataclass
class RuntimeGovernanceResult:
    decision: str
    reason: str
    source: str
    policy_group: str | None = None
    note: str | None = None


@dataclass
class SubstrateGovernanceResult:
    substrate: str
    decision: str
    reason: str
    source: str
    note: str | None = None


@dataclass
class CapabilityGovernanceOutcome:
    runtime_result: RuntimeGovernanceResult
    substrate_result: SubstrateGovernanceResult
    effective_outcome: str
    notes: dict[str, Any] | None = None


class CapabilityAttachPolicy(Protocol):
    def decide(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityAttachDecision:
        ...


class CapabilityGovernanceStack(Protocol):
    def evaluate(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
        tool_projection: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> CapabilityGovernanceOutcome:
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


class DetachedCapabilityGovernanceStack:
    def evaluate(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
        tool_projection: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> CapabilityGovernanceOutcome:
        metadata = tool_projection.get("metadata") if isinstance(tool_projection.get("metadata"), dict) else {}
        policy_group = str(metadata.get("policy_group") or "system_environment")
        approval_required = bool(tool_projection.get("requires_approval", False))
        environment_check_kind = str(metadata.get("environment_check_kind") or "none")
        environment_status = "ok"
        if environment_check_kind == "path_exists":
            path_value = input_payload.get("path")
            environment_status = "ok" if isinstance(path_value, str) and bool(path_value.strip()) else "unknown"
        structured = session.metadata.get("structured_reauthorization") if isinstance(session.metadata, dict) else {}
        has_structured_reauthorization = isinstance(structured, dict) and bool(structured.get(str(tool_projection.get("tool_name") or ""), {}).get("active"))
        decision = evaluate_tool_approval_policy(
            PolicyEvaluationInput(
                policy_group=policy_group,
                approval_required=approval_required,
                appearance_count_after_rejection=0,
                has_structured_reauthorization=has_structured_reauthorization,
                environment_status=environment_status,
                tool_name=str(tool_projection.get("tool_name") or "unknown_tool"),
            )
        )
        runtime_decision = "allow"
        if decision.outcome in {"deny", "recheck_environment", "loud_caution", "terminate_session"}:
            runtime_decision = "deny"
        elif decision.outcome == "require_approval":
            runtime_decision = "await_approval"
        runtime_result = RuntimeGovernanceResult(
            decision=runtime_decision,
            reason=decision.reason,
            source="detached_capability_governance_stack",
            policy_group=decision.policy_group,
            note=decision.explanation,
        )
        substrate = str(tool_projection.get("source") or "native")
        substrate_decision = "not_applicable"
        substrate_reason = "substrate_governance_not_yet_attached"
        if substrate == "mcp":
            substrate_decision = "allowed"
            substrate_reason = "mcp_governance_not_restricting_request"
            metadata_server = str(metadata.get("server_name") or "")
            if metadata_server == "filesystem":
                server_args = metadata.get("server_args") if isinstance(metadata.get("server_args"), list) else []
                server_env = metadata.get("server_env") if isinstance(metadata.get("server_env"), dict) else {}
                allowed_root = filesystem_server_allowed_root(server_args, server_env)
                target = resolve_filesystem_mcp_target_path(input_payload=input_payload, server_args=server_args, server_env=server_env)
                if allowed_root is None or target is None:
                    substrate_decision = "constrained"
                    substrate_reason = "filesystem_mcp_target_unknown"
                else:
                    try:
                        target.relative_to(allowed_root)
                    except ValueError:
                        substrate_decision = "denied"
                        substrate_reason = "filesystem_mcp_target_outside_allowed_root"
        substrate_result = SubstrateGovernanceResult(
            substrate=substrate,
            decision=substrate_decision,
            reason=substrate_reason,
            source="detached_capability_governance_stack",
        )
        effective_outcome = "execute"
        if runtime_result.decision == "await_approval":
            effective_outcome = "await_approval"
        elif runtime_result.decision != "allow" or substrate_result.decision not in {"allowed", "not_applicable"}:
            effective_outcome = "deny"
        return CapabilityGovernanceOutcome(
            runtime_result=runtime_result,
            substrate_result=substrate_result,
            effective_outcome=effective_outcome,
            notes={"runtime_profile": runtime_profile, "input_payload": input_payload},
        )
