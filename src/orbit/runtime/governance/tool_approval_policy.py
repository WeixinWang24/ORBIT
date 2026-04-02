from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PolicyGroup = Literal["permission_authority", "system_environment"]
PolicyOutcome = Literal[
    "allow",
    "require_approval",
    "deny",
    "loud_caution",
    "terminate_session",
    "recheck_environment",
]
PolicyScope = Literal["session", "turn"]
EnvironmentStatus = Literal["ok", "stale", "unknown", "denied"]


@dataclass
class PolicyEvaluationInput:
    policy_group: PolicyGroup
    approval_required: bool
    appearance_count_after_rejection: int
    has_structured_reauthorization: bool
    environment_status: EnvironmentStatus
    tool_name: str


@dataclass
class PolicyDecision:
    policy_group: PolicyGroup
    outcome: PolicyOutcome
    scope: PolicyScope
    reauthorization_required: bool
    reason: str
    explanation: str


def evaluate_tool_approval_policy(ctx: PolicyEvaluationInput) -> PolicyDecision:
    if ctx.policy_group == "permission_authority":
        return _evaluate_permission_authority(ctx)
    return _evaluate_system_environment(ctx)


def _evaluate_permission_authority(ctx: PolicyEvaluationInput) -> PolicyDecision:
    if not ctx.approval_required:
        return PolicyDecision(
            policy_group="permission_authority",
            outcome="allow",
            scope="session",
            reauthorization_required=False,
            reason="non_approval_case",
            explanation=f"{ctx.tool_name} does not currently require approval, so permission-authority escalation does not apply.",
        )

    if ctx.appearance_count_after_rejection <= 0:
        return PolicyDecision(
            policy_group="permission_authority",
            outcome="require_approval",
            scope="session",
            reauthorization_required=False,
            reason="initial_approval_request",
            explanation=f"{ctx.tool_name} is entering the normal approval path for this session.",
        )

    if ctx.has_structured_reauthorization:
        return PolicyDecision(
            policy_group="permission_authority",
            outcome="require_approval",
            scope="session",
            reauthorization_required=False,
            reason="structured_reauthorization_present",
            explanation=f"{ctx.tool_name} may re-enter the approval path because structured reauthorization is present.",
        )

    if ctx.appearance_count_after_rejection == 1:
        return PolicyDecision(
            policy_group="permission_authority",
            outcome="loud_caution",
            scope="session",
            reauthorization_required=True,
            reason="reappearance_without_reauthorization",
            explanation=f"{ctx.tool_name} reappeared after rejection without structured reauthorization; issue a loud caution.",
        )

    return PolicyDecision(
        policy_group="permission_authority",
        outcome="terminate_session",
        scope="session",
        reauthorization_required=True,
        reason="repeated_reappearance_without_reauthorization",
        explanation=f"{ctx.tool_name} reappeared repeatedly after rejection without structured reauthorization; terminate the session.",
    )


def _evaluate_system_environment(ctx: PolicyEvaluationInput) -> PolicyDecision:
    if ctx.environment_status in {"stale", "unknown"}:
        return PolicyDecision(
            policy_group="system_environment",
            outcome="recheck_environment",
            scope="turn",
            reauthorization_required=False,
            reason="environment_not_fresh",
            explanation=f"The current environment state for {ctx.tool_name} is not fresh enough; recheck environment conditions before proceeding.",
        )

    if ctx.environment_status == "denied":
        return PolicyDecision(
            policy_group="system_environment",
            outcome="deny",
            scope="turn",
            reauthorization_required=False,
            reason="environment_denied",
            explanation=f"Current environment conditions do not allow {ctx.tool_name}.",
        )

    if ctx.approval_required:
        return PolicyDecision(
            policy_group="system_environment",
            outcome="require_approval",
            scope="turn",
            reauthorization_required=False,
            reason="environment_ok_but_approval_required",
            explanation=f"Environment conditions are acceptable, but {ctx.tool_name} still requires approval.",
        )

    return PolicyDecision(
        policy_group="system_environment",
        outcome="allow",
        scope="turn",
        reauthorization_required=False,
        reason="environment_ok",
        explanation=f"Environment conditions are acceptable for {ctx.tool_name}.",
    )
