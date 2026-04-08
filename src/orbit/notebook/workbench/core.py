"""Notebook workbench helpers for ORBIT.

This workbench is now aligned to the active SessionManager-centered runtime
mainline. It can be constructed either from a live SessionManager or directly
from an OrbitStore when only notebook projection helpers are needed.
"""

from __future__ import annotations

import pandas as pd

from orbit.memory import MemoryService
from orbit.notebook.display.dataframes import approvals_dataframe, events_dataframe, session_messages_dataframe, session_turn_summary_dataframe, sessions_dataframe, steps_dataframe
from orbit.notebook.display.memory import memory_compare_backends_dataframe, memory_context_artifacts_dataframe, memory_embeddings_dataframe, memory_probe_dataframe, memory_records_dataframe, memory_scope_summary_dataframe, memory_status_summary_frame
from orbit.notebook.providers.memory_demo import memory_showcase_summary_frames
from orbit.runtime.core import SessionManager
from orbit.store.base import OrbitStore


class NotebookWorkbench:
    """High-level notebook helper facade for ORBIT runtime inspection/control.

    Mainline posture:
    - prefer construction from ``SessionManager`` when interacting with the
      active runtime
    - also allow direct ``OrbitStore`` construction for pure notebook analysis
      and deterministic fixture/test scenarios
    """

    def __init__(self, runtime: SessionManager | OrbitStore):
        if isinstance(runtime, SessionManager):
            self.session_manager: SessionManager | None = runtime
            self.store: OrbitStore = runtime.store
        else:
            self.session_manager = None
            self.store = runtime
        self.memory_service = MemoryService(store=self.store)

    @classmethod
    def from_store(cls, store: OrbitStore) -> "NotebookWorkbench":
        """Build a notebook workbench from a store-only inspection context."""
        return cls(store)

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

    def sessions_by_status_dataframe(self, status: str) -> pd.DataFrame:
        """Return sessions filtered by current session-level status semantics."""
        df = sessions_dataframe(self.store)
        if df.empty:
            return df
        normalized = str(status)
        if normalized == "waiting_for_approval":
            approvals = self.approvals_dataframe()
            if approvals.empty or "session_id" not in approvals.columns:
                return df.iloc[0:0].copy()
            waiting_ids = set(approvals["session_id"].dropna().astype(str).tolist())
            return df[df["session_id"].astype(str).isin(waiting_ids)].reset_index(drop=True)
        if "status" not in df.columns:
            return df.iloc[0:0].copy()
        return df[df["status"].astype(str) == normalized].reset_index(drop=True)

    def runs_summary_dataframe(self) -> pd.DataFrame:
        """Compatibility dashboard view backed by session-mainline truth."""
        df = self.sessions_dataframe().copy()
        if df.empty:
            return df
        approvals = self.approvals_dataframe()
        waiting_ids = set(approvals["session_id"].dropna().astype(str).tolist()) if not approvals.empty and "session_id" in approvals.columns else set()
        df["runtime_status"] = df["session_id"].astype(str).apply(lambda session_id: "waiting_for_approval" if session_id in waiting_ids else "active")
        return df

    def active_runs_dataframe(self) -> pd.DataFrame:
        """Compatibility helper: active sessions not currently waiting on approval."""
        df = self.runs_summary_dataframe()
        if df.empty or "runtime_status" not in df.columns:
            return df
        return df[df["runtime_status"] == "active"].reset_index(drop=True)

    def open_approval_runs_dataframe(self) -> pd.DataFrame:
        """Compatibility helper: sessions currently waiting on approval."""
        return self.sessions_by_status_dataframe("waiting_for_approval")

    def approval_requests_for_run_dataframe(self, run_id: str) -> pd.DataFrame:
        """Compatibility helper using conversation_id as the run/session bridge."""
        approvals = self.approvals_dataframe()
        if approvals.empty:
            return approvals
        if "conversation_id" in approvals.columns:
            return approvals[approvals["conversation_id"].astype(str) == str(run_id)].reset_index(drop=True)
        return approvals.iloc[0:0].copy()

    def run_summary_dataframe(self, run_id: str) -> pd.DataFrame:
        """Compatibility helper that projects one session row by conversation id."""
        df = self.runs_summary_dataframe()
        if df.empty or "conversation_id" not in df.columns:
            return df.iloc[0:0].copy() if not df.empty else pd.DataFrame()
        return df[df["conversation_id"].astype(str) == str(run_id)].reset_index(drop=True)

    def run_event_counts_dataframe(self, run_id: str) -> pd.DataFrame:
        """Compatibility helper summarizing events for one conversation id."""
        df = events_dataframe(self.store, run_id)
        if df.empty or "event_type" not in df.columns:
            return pd.DataFrame(columns=["event_type", "count"])
        grouped = df.groupby("event_type").size().reset_index(name="count")
        return grouped.sort_values(by=["event_type"]).reset_index(drop=True)

    def task_status_summary_dataframe(self) -> pd.DataFrame:
        """Session-mainline replacement for the old task dashboard summary."""
        df = self.sessions_dataframe()
        if df.empty:
            return pd.DataFrame(columns=["status", "count"])
        grouped = df.groupby("status").size().reset_index(name="count")
        return grouped.sort_values(by=["status"]).reset_index(drop=True)

    def run_status_summary_dataframe(self) -> pd.DataFrame:
        """Session-mainline replacement for run-status dashboard cards."""
        df = self.runs_summary_dataframe()
        if df.empty or "runtime_status" not in df.columns:
            return pd.DataFrame(columns=["runtime_status", "count"])
        grouped = df.groupby("runtime_status").size().reset_index(name="count")
        return grouped.sort_values(by=["runtime_status"]).reset_index(drop=True)

    def approval_summary_dataframe(self) -> pd.DataFrame:
        """Summarize currently open approval requests."""
        approvals = self.approvals_dataframe()
        if approvals.empty:
            return pd.DataFrame(columns=["tool_name", "count"])
        if "tool_name" not in approvals.columns:
            return pd.DataFrame(columns=["tool_name", "count"])
        grouped = approvals.groupby("tool_name").size().reset_index(name="count")
        return grouped.sort_values(by=["tool_name"]).reset_index(drop=True)

    def events_for_sessions_dataframe(self, session_ids: list[str]) -> pd.DataFrame:
        """Project execution events for a set of session ids through conversation ids."""
        rows: list[pd.DataFrame] = []
        for session_id in session_ids:
            session = self.store.get_session(session_id)
            if session is None:
                continue
            df = events_dataframe(self.store, session.conversation_id)
            if not df.empty:
                rows.append(df)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    def events_for_runs_dataframe(self, run_ids: list[str]) -> pd.DataFrame:
        """Compatibility alias using conversation ids as run identifiers."""
        rows: list[pd.DataFrame] = []
        for run_id in run_ids:
            df = events_dataframe(self.store, run_id)
            if not df.empty:
                rows.append(df)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    def session_messages_dataframe(self, session_id: str) -> pd.DataFrame:
        return session_messages_dataframe(self.store, session_id)

    def session_turn_summary_dataframe(self, session_id: str) -> pd.DataFrame:
        return session_turn_summary_dataframe(self.store, session_id)

    def events_dataframe(self, run_id: str) -> pd.DataFrame:
        return events_dataframe(self.store, run_id)

    def steps_dataframe(self, run_id: str) -> pd.DataFrame:
        return steps_dataframe(self.store, run_id)

    def approvals_dataframe(self) -> pd.DataFrame:
        if self.session_manager is not None:
            approvals = self.session_manager.list_open_session_approvals()
            rows = []
            for approval in approvals:
                tool_request = approval.get("tool_request", {}) if isinstance(approval, dict) else {}
                rows.append(
                    {
                        "approval_request_id": approval.get("approval_request_id"),
                        "session_id": approval.get("session_id"),
                        "conversation_id": approval.get("conversation_id"),
                        "tool_name": tool_request.get("tool_name"),
                        "side_effect_class": tool_request.get("side_effect_class"),
                        "opened_at": approval.get("opened_at"),
                        "source_backend": approval.get("source_backend"),
                        "plan_label": approval.get("plan_label"),
                    }
                )
            return pd.DataFrame(rows)
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
        if self.session_manager is None:
            raise ValueError("NotebookWorkbench.approve requires a live SessionManager")
        approvals = self.session_manager.list_open_session_approvals()
        approval = next((item for item in approvals if item.get("approval_request_id") == approval_request_id), None)
        if approval is None:
            raise ValueError(f"approval request not found: {approval_request_id}")
        return self.session_manager.resolve_session_approval(
            session_id=approval["session_id"],
            approval_request_id=approval_request_id,
            decision="approve",
            note=note,
        )

    def reject(self, approval_request_id: str, note: str = "rejected from notebook"):
        if self.session_manager is None:
            raise ValueError("NotebookWorkbench.reject requires a live SessionManager")
        approvals = self.session_manager.list_open_session_approvals()
        approval = next((item for item in approvals if item.get("approval_request_id") == approval_request_id), None)
        if approval is None:
            raise ValueError(f"approval request not found: {approval_request_id}")
        return self.session_manager.resolve_session_approval(
            session_id=approval["session_id"],
            approval_request_id=approval_request_id,
            decision="reject",
            note=note,
        )
