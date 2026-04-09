from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orbit.models import GovernedToolState, MessageRole
from orbit.models.core import new_id
from orbit.runtime.core.events import RuntimeEventType
from orbit.runtime.execution.contracts.plans import ExecutionPlan
from orbit.runtime.governance.tool_approval_policy import PolicyDecision, PolicyEvaluationInput, evaluate_tool_approval_policy
from orbit.runtime.extensions.metadata_channels import capability_metadata


class ToolGovernanceService:
    """Governance-surface owner for tool approval, reauthorization, and governed-tool tracking."""

    def __init__(self, session_manager) -> None:
        self.session_manager = session_manager

    def has_structured_reauthorization(self, *, session, tool_name: str) -> bool:
        structured = session.metadata.get("structured_reauthorization")
        if not isinstance(structured, dict):
            return False
        tool_record = structured.get(tool_name)
        return isinstance(tool_record, dict) and bool(tool_record.get("active"))

    def mark_permission_rejection(self, *, session, tool_name: str) -> None:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        permission_tracking[tool_name] = {
            "rejection_active": True,
            "appearance_count_after_rejection": 0,
        }
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

    def get_appearance_count_after_rejection(self, *, session, tool_name: str) -> int:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        return int(tool_tracking.get("appearance_count_after_rejection", 0))

    def increment_reappearance_after_rejection(self, *, session, tool_name: str) -> int:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        if tool_tracking.get("rejection_active"):
            tool_tracking["appearance_count_after_rejection"] = int(tool_tracking.get("appearance_count_after_rejection", 0)) + 1
            session.updated_at = datetime.now(timezone.utc)
            self.session_manager.store.save_session(session)
        return int(tool_tracking.get("appearance_count_after_rejection", 0))

    def resolve_environment_status(self, tool_request) -> str:
        governance = self.session_manager._get_tool_governance_metadata(tool_request.tool_name)
        check_kind = governance.get("environment_check_kind", "none")
        if check_kind == "none":
            return "ok"
        if check_kind == "path_exists":
            path = tool_request.input_payload.get("path")
            if not path:
                tool = self.session_manager.tool_registry.get(tool_request.tool_name)
                if getattr(tool, "tool_source", None) == "mcp" and getattr(tool, "original_name", None) in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                    path = "."
                    tool_request.input_payload["path"] = path
                else:
                    return "unknown"

            tool = self.session_manager.tool_registry.get(tool_request.tool_name)
            if getattr(tool, "tool_source", None) == "mcp" and getattr(tool, "original_name", None) in {"read_file", "list_directory", "list_directory_with_sizes", "directory_tree", "search_files", "get_file_info"}:
                client = getattr(tool, "client", None)
                bootstrap = getattr(client, "bootstrap", None) if client is not None else None
                server_args = getattr(bootstrap, "args", []) if bootstrap is not None else []
                server_env = getattr(bootstrap, "env", {}) if bootstrap is not None else {}
                from orbit.runtime.mcp.governance import resolve_filesystem_mcp_target_path
                target = resolve_filesystem_mcp_target_path(
                    input_payload=tool_request.input_payload,
                    server_args=server_args,
                    server_env=server_env,
                )
                allowed_root = Path(server_env["ORBIT_WORKSPACE_ROOT"]).resolve() if server_env.get("ORBIT_WORKSPACE_ROOT") else None
                if allowed_root is None and server_args:
                    allowed_root = Path(server_args[-1]).resolve()
                if target is None or allowed_root is None:
                    return "unknown"
                try:
                    target.relative_to(allowed_root)
                except ValueError:
                    return "denied"
                original_name = getattr(tool, "original_name", None)
                if original_name in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                    return "ok" if target.exists() and target.is_dir() else "denied"
                return "ok" if target.exists() and target.is_file() else "denied"

            workspace_root = Path(self.session_manager.workspace_root).resolve()
            target = (workspace_root / path).resolve()
            if not str(target).startswith(str(workspace_root)):
                return "denied"
            return "ok" if target.exists() and target.is_file() else "denied"
        return "unknown"

    def evaluate_policy_for_plan(self, *, session, plan, rejected_tool_name: str | None):
        if plan.tool_request is None:
            raise ValueError("policy evaluation requires a tool request")

        tool_request = plan.tool_request
        governance = self.session_manager._get_tool_governance_metadata(tool_request.tool_name)
        policy_group = governance["policy_group"]
        appearance_count_after_rejection = self.increment_reappearance_after_rejection(
            session=session,
            tool_name=tool_request.tool_name,
        )
        environment_status = self.resolve_environment_status(tool_request)
        ctx = PolicyEvaluationInput(
            policy_group=policy_group,
            approval_required=tool_request.requires_approval,
            appearance_count_after_rejection=appearance_count_after_rejection,
            has_structured_reauthorization=self.has_structured_reauthorization(session=session, tool_name=tool_request.tool_name),
            environment_status=environment_status,
            tool_name=tool_request.tool_name,
        )
        return evaluate_tool_approval_policy(ctx)

    def set_governed_tool_state(self, session, state: GovernedToolState | None) -> None:
        session.governed_tool_state = state
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

    def transition_governed_state(self, session, new_state: str, *, note: str | None = None) -> None:
        current = session.governed_tool_state
        if current is None:
            raise ValueError(f"session has no governed tool state to transition: {session.session_id}")
        self.set_governed_tool_state(session, current.transition(new_state, note=note))

    def set_pending_approval(self, session, pending: dict) -> None:
        capability_metadata(session.metadata)["pending_approval"] = pending
        governed_state = GovernedToolState(
            tool_name=pending["tool_request"].get("tool_name", "unknown"),
            state="waiting_for_approval",
            approval_request_id=pending.get("approval_request_id"),
            side_effect_class=pending["tool_request"].get("side_effect_class", "safe"),
            input_payload=pending["tool_request"].get("input_payload", {}),
        )
        self.set_governed_tool_state(session, governed_state)

    def clear_pending_approval(self, session) -> None:
        capability_metadata(session.metadata).pop("pending_approval", None)
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

    def open_session_approval(self, *, session, tool_request, plan: ExecutionPlan) -> ExecutionPlan:
        approval_request_id = new_id("approval")
        pending = {
            "approval_request_id": approval_request_id,
            "tool_request": tool_request.model_dump(mode="json"),
            "source_backend": plan.source_backend,
            "plan_label": plan.plan_label,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self.set_pending_approval(session, pending)
        self.session_manager.emit_session_event(
            session_id=session.session_id,
            event_type=RuntimeEventType.APPROVAL_REQUESTED,
            payload={
                "approval_request_id": approval_request_id,
                "tool_name": tool_request.tool_name,
                "side_effect_class": tool_request.side_effect_class,
                "source_backend": plan.source_backend,
                "plan_label": plan.plan_label,
            },
        )
        approval_text = (
            f"Approval required before executing {tool_request.tool_name} "
            f"(side_effect_class={tool_request.side_effect_class})."
        )
        self.session_manager.append_message(
            session_id=session.session_id,
            role=MessageRole.ASSISTANT,
            content=approval_text,
            metadata={
                "message_kind": "approval_request",
                "approval_request_id": approval_request_id,
                "tool_name": tool_request.tool_name,
                "side_effect_class": tool_request.side_effect_class,
                "source_backend": plan.source_backend,
                "plan_label": plan.plan_label,
            },
        )
        return ExecutionPlan(
            source_backend=plan.source_backend,
            plan_label=f"{plan.plan_label}-waiting-for-approval",
            tool_request=tool_request,
            should_finish_after_tool=False,
            failure_reason=None,
        )

    def build_policy_message_outcome_spec(self, *, tool_request, decision: PolicyDecision) -> dict:
        if decision.outcome not in {"loud_caution", "terminate_session"}:
            raise ValueError(f"unsupported policy message outcome: {decision.outcome}")
        artifact_type = "session_policy_caution" if decision.outcome == "loud_caution" else "session_policy_termination"
        event_kind = "policy_caution" if decision.outcome == "loud_caution" else "policy_termination"
        message_kind = "policy_caution" if decision.outcome == "loud_caution" else "policy_termination"
        plan_suffix = "policy-caution" if decision.outcome == "loud_caution" else "terminated"
        return {
            "termination_requested": decision.outcome == "terminate_session",
            "artifact_type": artifact_type,
            "artifact_content": f"tool_name={tool_request.tool_name}\npolicy_group={decision.policy_group}\nreason={decision.reason}",
            "event_payload": {
                "kind": event_kind,
                "tool_name": tool_request.tool_name,
                "policy_group": decision.policy_group,
                "reason": decision.reason,
            },
            "message_content": decision.explanation,
            "message_metadata": {
                "message_kind": message_kind,
                "policy_group": decision.policy_group,
                "tool_name": tool_request.tool_name,
                "reason": decision.reason,
            },
            "plan_suffix": plan_suffix,
        }

    def build_policy_failure_outcome_spec(self, *, tool_request, decision: PolicyDecision) -> dict:
        if decision.outcome not in {"deny", "recheck_environment"}:
            raise ValueError(f"unsupported policy failure outcome: {decision.outcome}")
        return {
            "invocation_failure_payload": {
                "ok": False,
                "content": decision.explanation,
                "data": {
                    "failure_kind": "policy_decision",
                    "policy_group": decision.policy_group,
                    "reason": decision.reason,
                    "outcome": decision.outcome,
                },
            },
            "artifact_type": "session_policy_decision",
            "artifact_content": f"tool_name={tool_request.tool_name}\npolicy_group={decision.policy_group}\nreason={decision.reason}\noutcome={decision.outcome}",
            "event_payload": {
                "kind": "policy_decision",
                "tool_name": tool_request.tool_name,
                "policy_group": decision.policy_group,
                "reason": decision.reason,
                "outcome": decision.outcome,
            },
            "message_content": decision.explanation,
            "message_metadata": {
                "message_kind": "policy_decision",
                "policy_group": decision.policy_group,
                "tool_name": tool_request.tool_name,
                "reason": decision.reason,
                "outcome": decision.outcome,
            },
            "plan_suffix": decision.outcome,
        }

    def reauthorize_tool_path(
        self,
        *,
        session_id: str,
        tool_name: str,
        note: str | None = None,
        source: str = "runtime_entry",
    ) -> dict:
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        if (session.metadata.get("core_runtime_metadata") or {}).get("terminated"):
            raise ValueError(f"cannot reauthorize terminated session: {session_id}")

        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        tool_tracking["rejection_active"] = False
        tool_tracking["appearance_count_after_rejection"] = 0

        structured = session.metadata.setdefault("structured_reauthorization", {})
        record = {
            "active": True,
            "source": source,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        structured[tool_name] = record
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

        message_text = f"Structured reauthorization recorded for {tool_name}. Future requests for this tool may re-enter the governed approval path."
        if note:
            message_text += f" Note: {note}"
        self.session_manager.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="session_structured_reauthorization",
            content=f"tool_name={tool_name}\nsource={source}\nnote={note or ''}",
            source="governance",
        )
        self.session_manager.emit_session_event(
            session_id=session_id,
            event_type=RuntimeEventType.APPROVAL_GRANTED,
            payload={"kind": "structured_reauthorization", "tool_name": tool_name, "source": source},
        )
        self.session_manager.append_message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=message_text,
            metadata={
                "message_kind": "structured_reauthorization",
                "tool_name": tool_name,
                "source": source,
                "note": note,
            },
        )
        return {
            "session_id": session_id,
            "tool_name": tool_name,
            "source": source,
            "note": note,
            **record,
        }
