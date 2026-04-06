"""Notebook workbench helpers for ORBIT."""

from __future__ import annotations

import pandas as pd

from orbit.memory import MemoryService
from orbit.notebook.display.dataframes import approvals_dataframe, events_dataframe, session_messages_dataframe, session_turn_summary_dataframe, sessions_dataframe, steps_dataframe
from orbit.notebook.display.memory import memory_compare_backends_dataframe, memory_context_artifacts_dataframe, memory_embeddings_dataframe, memory_probe_dataframe, memory_records_dataframe, memory_scope_summary_dataframe, memory_status_summary_frame
from orbit.notebook.providers.memory_demo import memory_showcase_summary_frames
from orbit.runtime.historical import OrbitCoordinator
from orbit.store.base import OrbitStore


class NotebookWorkbench:
    """High-level notebook helper facade for ORBIT runtime inspection/control."""

    def __init__(self, coordinator: OrbitCoordinator):
        self.coordinator = coordinator
        self.store: OrbitStore = coordinator.store
        self.memory_service = MemoryService(store=self.store)

    def tasks_dataframe(self) -> pd.DataFrame:
        tasks = self.store.list_tasks()
        rows = []
        for task in tasks:
            rows.append({"task_id": task.task_id, "title": task.title, "description": task.description, "status": task.status, "created_at": task.created_at, "updated_at": task.updated_at, "tags": task.tags})
        return pd.DataFrame(rows)

    def runs_dataframe(self) -> pd.DataFrame:
        runs = self.store.list_runs()
        rows = []
        for run in runs:
            rows.append({"run_id": run.run_id, "task_id": run.task_id, "status": run.status, "created_at": run.created_at, "started_at": run.started_at, "ended_at": run.ended_at, "current_step_id": run.current_step_id, "result_summary": run.result_summary, "failure_reason": run.failure_reason})
        return pd.DataFrame(rows)

    def sessions_dataframe(self) -> pd.DataFrame:
        return sessions_dataframe(self.store)

    def session_messages_dataframe(self, session_id: str) -> pd.DataFrame:
        return session_messages_dataframe(self.store, session_id)

    def session_turn_summary_dataframe(self, session_id: str) -> pd.DataFrame:
        return session_turn_summary_dataframe(self.store, session_id)

    def events_dataframe(self, run_id: str) -> pd.DataFrame:
        return events_dataframe(self.store, run_id)

    def steps_dataframe(self, run_id: str) -> pd.DataFrame:
        return steps_dataframe(self.store, run_id)

    def approvals_dataframe(self) -> pd.DataFrame:
        return approvals_dataframe(self.store)

    def memory_records_dataframe(self, *, session_id: str | None = None, scope: str | None = None, limit: int = 200) -> pd.DataFrame:
        return memory_records_dataframe(self.store, session_id=session_id, scope=scope, limit=limit)

    def memory_embeddings_dataframe(self, *, session_id: str | None = None, model_name: str | None = None, limit: int = 200) -> pd.DataFrame:
        return memory_embeddings_dataframe(self.store, session_id=session_id, model_name=model_name, limit=limit)

    def memory_probe_dataframe(self, *, session_id: str | None, query_text: str, limit: int = 5, scope: str = "all", backend_override: str | None = None) -> pd.DataFrame:
        return memory_probe_dataframe(
            self.store,
            session_id=session_id,
            query_text=query_text,
            limit=limit,
            scope=scope,
            memory_service=self.memory_service,
            backend_override=backend_override,
        )

    def memory_scope_summary_dataframe(self, *, session_id: str | None = None, limit: int = 200) -> pd.DataFrame:
        return memory_scope_summary_dataframe(self.store, session_id=session_id, limit=limit)

    def memory_compare_backends_dataframe(self, *, session_id: str | None, query_text: str, limit: int = 5, scope: str = "all") -> pd.DataFrame:
        return memory_compare_backends_dataframe(
            self.store,
            session_id=session_id,
            query_text=query_text,
            limit=limit,
            scope=scope,
            memory_service=self.memory_service,
        )

    def memory_context_artifacts_dataframe(self, run_id: str, *, artifact_type: str | None = None) -> pd.DataFrame:
        return memory_context_artifacts_dataframe(self.store, run_id, artifact_type=artifact_type)

    def memory_summary_frames(self, *, session_id: str, query_text: str, limit: int = 10) -> dict[str, object]:
        """Return the unified memory notebook bundle for one session/query pair."""
        session = next((item for item in self.store.list_sessions() if item.session_id == session_id), None)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        return memory_showcase_summary_frames(
            store=self.store,
            service=self.memory_service,
            session=session,
            query_text=query_text,
        )

    def memory_status_summary_frame(self, *, session_id: str, query_text: str) -> pd.DataFrame:
        """Return the one-row rendered status card for a session/query memory view."""
        frames = self.memory_summary_frames(session_id=session_id, query_text=query_text)
        return memory_status_summary_frame(frames["summary"])

    def approve(self, approval_request_id: str, note: str = "approved from notebook"):
        return self.coordinator.resolve_approval(approval_request_id, "approve", note)

    def reject(self, approval_request_id: str, note: str = "rejected from notebook"):
        return self.coordinator.resolve_approval(approval_request_id, "reject", note)
