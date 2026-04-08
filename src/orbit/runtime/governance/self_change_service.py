from __future__ import annotations

from datetime import datetime, timezone

from orbit.models import ExecutionEvent


class SelfChangeGovernanceService:
    """Governance-surface owner for bounded self-change planning.

    This service adapts the host runtime nucleus (`SessionManager`) rather than
    asking the nucleus to own self-change lifecycle management directly.
    """

    def __init__(self, session_manager) -> None:
        self.session_manager = session_manager

    def _require_evo_mode(self, operation: str) -> None:
        if self.session_manager.runtime_mode != "evo":
            raise ValueError(
                f"{operation} requires evo mode (current mode: {self.session_manager.runtime_mode})"
            )

    def _save_self_change_plan_artifact(self, session_id: str, plan) -> None:
        self.session_manager.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="self_change_plan",
            content=plan.model_dump_json(indent=2),
            source="self_change_lifecycle",
        )

    def _update_session_self_change_summary(self, session, plan) -> None:
        session.metadata["self_change"] = {
            "active_plan_id": plan.plan_id if plan.status in {"planned", "approved", "active"} else None,
            "last_plan": {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "status": plan.status,
                "updated_at": plan.updated_at.isoformat(),
            },
        }
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

    def create_plan(
        self,
        *,
        session_id: str,
        title: str,
        description: str,
        metadata: dict | None = None,
    ):
        from orbit.models.builds import SelfChangePlan

        self._require_evo_mode("create_self_change_plan")
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        plan = SelfChangePlan(
            session_id=session_id,
            title=title,
            description=description,
            metadata=metadata or {},
        )
        self._save_self_change_plan_artifact(session_id, plan)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="self_change_plan_created",
            payload={"plan_id": plan.plan_id, "title": plan.title, "status": plan.status},
        )
        self.session_manager.store.save_event(event)
        self._update_session_self_change_summary(session, plan)
        return plan

    def get_active_plan_id(self, *, session_id: str):
        session = self.session_manager.get_session(session_id)
        if session is None:
            return None
        sc = session.metadata.get("self_change", {}) if isinstance(session.metadata, dict) else {}
        return sc.get("active_plan_id")

    def update_plan_status(
        self,
        *,
        session_id: str,
        plan,
        status: str,
    ):
        self._require_evo_mode("update_self_change_plan_status")
        valid_statuses = {"planned", "approved", "active", "blocked", "completed", "abandoned", "superseded"}
        if status not in valid_statuses:
            raise ValueError(f"invalid self_change_plan status: {status!r}")
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        updated = plan.with_status(status)
        self._save_self_change_plan_artifact(session_id, updated)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="self_change_plan_status_changed",
            payload={"plan_id": updated.plan_id, "old_status": plan.status, "new_status": status},
        )
        self.session_manager.store.save_event(event)
        self._update_session_self_change_summary(session, updated)
        return updated

    def has_active_evo_self_change(self, *, session_id: str) -> bool:
        if self.session_manager.runtime_mode != "evo":
            return False
        active = self.get_active_plan_id(session_id=session_id)
        return active is not None
