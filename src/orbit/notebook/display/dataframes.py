"""Notebook DataFrame projection helpers for ORBIT runtime artifacts."""

from __future__ import annotations

import pandas as pd

from orbit.store.base import OrbitStore


def events_dataframe(store: OrbitStore, run_id: str) -> pd.DataFrame:
    events = store.list_events_for_run(run_id)
    rows = []
    for event in events:
        rows.append({"event_id": event.event_id, "run_id": event.run_id, "event_type": event.event_type, "timestamp": event.timestamp, "step_id": event.step_id, "severity": event.severity, "payload": event.payload})
    return pd.DataFrame(rows)


def steps_dataframe(store: OrbitStore, run_id: str) -> pd.DataFrame:
    steps = store.list_steps_for_run(run_id)
    rows = []
    for step in steps:
        rows.append({"step_id": step.step_id, "run_id": step.run_id, "index": step.index, "step_type": step.step_type, "status": step.status, "started_at": step.started_at, "ended_at": step.ended_at})
    return pd.DataFrame(rows)


def approvals_dataframe(store: OrbitStore) -> pd.DataFrame:
    approvals = store.list_open_approval_requests()
    rows = []
    for approval in approvals:
        rows.append({"approval_request_id": approval.approval_request_id, "run_id": approval.run_id, "step_id": approval.step_id, "target_type": approval.target_type, "target_id": approval.target_id, "risk_level": approval.risk_level, "status": approval.status, "created_at": approval.created_at, "reason": approval.reason})
    return pd.DataFrame(rows)


def sessions_dataframe(store: OrbitStore) -> pd.DataFrame:
    sessions = store.list_sessions()
    rows = []
    for session in sessions:
        rows.append({"session_id": session.session_id, "conversation_id": session.conversation_id, "backend_name": session.backend_name, "model": session.model, "status": session.status, "created_at": session.created_at, "updated_at": session.updated_at})
    return pd.DataFrame(rows)


def session_messages_dataframe(store: OrbitStore, session_id: str) -> pd.DataFrame:
    messages = store.list_messages_for_session(session_id)
    rows = []
    for message in messages:
        rows.append({"message_id": message.message_id, "session_id": message.session_id, "turn_index": message.turn_index, "role": message.role, "content": message.content, "created_at": message.created_at, "provider_message_id": message.provider_message_id, "metadata": message.metadata})
    return pd.DataFrame(rows)


def session_turn_summary_dataframe(store: OrbitStore, session_id: str) -> pd.DataFrame:
    df = session_messages_dataframe(store, session_id)
    if df.empty:
        return pd.DataFrame(columns=["turn_index", "roles", "message_count"])
    grouped = df.groupby("turn_index").agg(roles=("role", lambda s: ", ".join([str(v) for v in s.tolist()])), message_count=("message_id", "count")).reset_index()
    return grouped.sort_values(by=["turn_index"]).reset_index(drop=True)
