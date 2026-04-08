from __future__ import annotations

from datetime import datetime, timezone

from orbit.models import ExecutionEvent


class BuildOperationService:
    """Operation-surface owner for build lifecycle tracking and validation workflow.

    This service adapts the host runtime nucleus (`SessionManager`) rather than
    asking the nucleus to own build-operation lifecycle management directly.
    """

    def __init__(self, session_manager) -> None:
        self.session_manager = session_manager

    def _require_evo_mode(self, operation: str) -> None:
        if self.session_manager.runtime_mode != "evo":
            raise ValueError(
                f"{operation} requires evo mode (current mode: {self.session_manager.runtime_mode})"
            )

    def _save_build_record_artifact(self, session_id: str, record) -> None:
        self.session_manager.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="build_record",
            content=record.model_dump_json(indent=2),
            source="build_lifecycle",
        )

    def _update_session_build_summary(self, session, record) -> None:
        session.metadata["build_management"] = {
            "active_build_id": record.build_id if record.status in {"planned", "validating"} else None,
            "last_build": {
                "build_id": record.build_id,
                "status": record.status,
                "summary": record.summary,
                "updated_at": record.updated_at.isoformat(),
            },
        }
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)

    def create_build_record(
        self,
        *,
        session_id: str,
        linked_plan_id: str | None = None,
        summary: str = "",
        metadata: dict | None = None,
    ):
        from orbit.models.builds import BuildRecord

        self._require_evo_mode("create_build_record")
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        record = BuildRecord(
            session_id=session_id,
            linked_plan_id=linked_plan_id,
            summary=summary,
            metadata=metadata or {},
        )
        self._save_build_record_artifact(session_id, record)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="build_record_created",
            payload={"build_id": record.build_id, "linked_plan_id": linked_plan_id, "status": record.status},
        )
        self.session_manager.store.save_event(event)
        self._update_session_build_summary(session, record)
        return record

    def get_active_build_record_id(self, *, session_id: str) -> str | None:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return None
        bm = session.metadata.get("build_management", {}) if isinstance(session.metadata, dict) else {}
        return bm.get("active_build_id")

    def start_validation(self, *, session_id: str, record):
        self._require_evo_mode("start_build_validation")
        if record.status != "planned":
            raise ValueError(
                f"cannot start validation for build record in status {record.status!r} (expected 'planned')"
            )
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        updated = record.with_status("validating")
        self._save_build_record_artifact(session_id, updated)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="build_validation_started",
            payload={"build_id": updated.build_id},
        )
        self.session_manager.store.save_event(event)
        self._update_session_build_summary(session, updated)
        return updated

    def append_validation_step(
        self,
        *,
        session_id: str,
        record,
        step_name: str,
        status: str,
        output: str = "",
    ):
        from orbit.models.builds import ValidationStep

        self._require_evo_mode("append_build_validation_step")
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        step = ValidationStep(step_name=step_name, status=status, output=output)  # type: ignore[arg-type]
        updated = record.with_validation_step(step)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="build_validation_step_appended",
            payload={"build_id": updated.build_id, "step_name": step_name, "status": status},
        )
        self.session_manager.store.save_event(event)
        self._update_session_build_summary(session, updated)
        return updated

    def finalize_build(
        self,
        *,
        session_id: str,
        record,
        verdict: str,
        summary: str = "",
    ):
        self._require_evo_mode("finalize_build_record")
        if verdict not in {"passed", "failed", "blocked"}:
            raise ValueError(f"invalid build verdict: {verdict!r}")
        if record.status not in {"planned", "validating"}:
            raise ValueError(
                f"cannot finalize build record in status {record.status!r} (expected 'planned' or 'validating')"
            )
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        now = datetime.now(timezone.utc)
        updated = record.model_copy(update={
            "status": verdict,
            "summary": summary or record.summary,
            "finalized_at": now,
            "updated_at": now,
        })
        self._save_build_record_artifact(session_id, updated)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="build_record_finalized",
            payload={"build_id": updated.build_id, "verdict": verdict, "summary": summary},
        )
        self.session_manager.store.save_event(event)
        self._update_session_build_summary(session, updated)
        return updated

    def mark_rolled_back(self, *, session_id: str, record):
        self._require_evo_mode("mark_build_rolled_back")
        if record.status == "rolled_back":
            raise ValueError("build record is already rolled_back")
        session = self.session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        now = datetime.now(timezone.utc)
        updated = record.model_copy(update={
            "status": "rolled_back",
            "rolled_back_at": now,
            "updated_at": now,
        })
        self._save_build_record_artifact(session_id, updated)
        event = ExecutionEvent(
            run_id=session.conversation_id,
            event_type="build_record_rolled_back",
            payload={"build_id": updated.build_id},
        )
        self.session_manager.store.save_event(event)
        self._update_session_build_summary(session, updated)
        return updated
