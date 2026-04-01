"""Notebook workbench helpers for ORBIT."""

from __future__ import annotations

import pandas as pd

from orbit.notebook.display.dataframes import approvals_dataframe, events_dataframe, session_messages_dataframe, session_turn_summary_dataframe, sessions_dataframe, steps_dataframe
from orbit.runtime import OrbitCoordinator
from orbit.store.base import OrbitStore


class NotebookWorkbench:
    """High-level notebook helper facade for ORBIT runtime inspection/control."""

    def __init__(self, coordinator: OrbitCoordinator):
        self.coordinator = coordinator
        self.store: OrbitStore = coordinator.store

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

    def approve(self, approval_request_id: str, note: str = "approved from notebook"):
        return self.coordinator.resolve_approval(approval_request_id, "approve", note)

    def reject(self, approval_request_id: str, note: str = "rejected from notebook"):
        return self.coordinator.resolve_approval(approval_request_id, "reject", note)
