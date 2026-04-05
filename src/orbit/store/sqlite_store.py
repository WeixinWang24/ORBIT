"""SQLite-backed bootstrap store for ORBIT."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from orbit.models import (
    ApprovalDecision,
    ApprovalRequest,
    ContextArtifact,
    ConversationMessage,
    ConversationSession,
    ExecutionEvent,
    ManagedProcess,
    Run,
    RunStep,
    Task,
    ToolInvocation,
)
from orbit.store.base import OrbitStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_steps (step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_index INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tool_invocations (tool_invocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approval_requests (approval_request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approval_decisions (approval_decision_id TEXT PRIMARY KEY, approval_request_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS context_artifacts (context_artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS managed_processes (process_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS session_messages (message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_index INTEGER NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
"""


class SQLiteStore(OrbitStore):
    """SQLite implementation of the ORBIT persistence boundary."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @staticmethod
    def _dump(model) -> str:
        return model.model_dump_json()

    def save_task(self, task: Task) -> None:
        self.conn.execute("INSERT OR REPLACE INTO tasks(task_id, data) VALUES (?, ?)", (task.task_id, self._dump(task)))
        self.conn.commit()

    def save_run(self, run: Run) -> None:
        self.conn.execute("INSERT OR REPLACE INTO runs(run_id, task_id, data) VALUES (?, ?, ?)", (run.run_id, run.task_id, self._dump(run)))
        self.conn.commit()

    def save_step(self, step: RunStep) -> None:
        self.conn.execute("INSERT OR REPLACE INTO run_steps(step_id, run_id, step_index, data) VALUES (?, ?, ?, ?)", (step.step_id, step.run_id, step.index, self._dump(step)))
        self.conn.commit()

    def save_event(self, event: ExecutionEvent) -> None:
        self.conn.execute("INSERT OR REPLACE INTO events(event_id, run_id, timestamp, data) VALUES (?, ?, ?, ?)", (event.event_id, event.run_id, event.timestamp.isoformat(), self._dump(event)))
        self.conn.commit()

    def save_tool_invocation(self, tool: ToolInvocation) -> None:
        self.conn.execute("INSERT OR REPLACE INTO tool_invocations(tool_invocation_id, run_id, data) VALUES (?, ?, ?)", (tool.tool_invocation_id, tool.run_id, self._dump(tool)))
        self.conn.commit()

    def save_approval_request(self, request: ApprovalRequest) -> None:
        self.conn.execute("INSERT OR REPLACE INTO approval_requests(approval_request_id, run_id, data) VALUES (?, ?, ?)", (request.approval_request_id, request.run_id, self._dump(request)))
        self.conn.commit()

    def save_approval_decision(self, decision: ApprovalDecision) -> None:
        self.conn.execute("INSERT OR REPLACE INTO approval_decisions(approval_decision_id, approval_request_id, data) VALUES (?, ?, ?)", (decision.approval_decision_id, decision.approval_request_id, self._dump(decision)))
        self.conn.commit()

    def save_context_artifact(self, artifact: ContextArtifact) -> None:
        self.conn.execute("INSERT OR REPLACE INTO context_artifacts(context_artifact_id, run_id, data) VALUES (?, ?, ?)", (artifact.context_artifact_id, artifact.run_id, self._dump(artifact)))
        self.conn.commit()

    def save_session(self, session: ConversationSession) -> None:
        self.conn.execute("INSERT OR REPLACE INTO sessions(session_id, conversation_id, updated_at, data) VALUES (?, ?, ?, ?)", (session.session_id, session.conversation_id, session.updated_at.isoformat(), self._dump(session)))
        self.conn.commit()

    def save_managed_process(self, process: ManagedProcess) -> None:
        self.conn.execute("INSERT OR REPLACE INTO managed_processes(process_id, session_id, updated_at, data) VALUES (?, ?, ?, ?)", (process.process_id, process.session_id, process.updated_at.isoformat(), self._dump(process)))
        self.conn.commit()

    def save_message(self, message: ConversationMessage) -> None:
        self.conn.execute("INSERT OR REPLACE INTO session_messages(message_id, session_id, turn_index, created_at, data) VALUES (?, ?, ?, ?, ?)", (message.message_id, message.session_id, message.turn_index, message.created_at.isoformat(), self._dump(message)))
        self.conn.commit()

    def list_tasks(self) -> list[Task]:
        rows = self.conn.execute("SELECT data FROM tasks ORDER BY rowid ASC").fetchall()
        return [Task.model_validate_json(row["data"]) for row in rows]

    def list_runs(self) -> list[Run]:
        rows = self.conn.execute("SELECT data FROM runs ORDER BY rowid ASC").fetchall()
        return [Run.model_validate_json(row["data"]) for row in rows]

    def list_sessions(self) -> list[ConversationSession]:
        rows = self.conn.execute("SELECT data FROM sessions ORDER BY updated_at DESC, rowid DESC").fetchall()
        return [ConversationSession.model_validate_json(row["data"]) for row in rows]

    def list_managed_processes(self) -> list[ManagedProcess]:
        rows = self.conn.execute("SELECT data FROM managed_processes ORDER BY updated_at ASC, rowid ASC").fetchall()
        return [ManagedProcess.model_validate_json(row["data"]) for row in rows]

    def list_messages_for_session(self, session_id: str) -> list[ConversationMessage]:
        rows = self.conn.execute("SELECT data FROM session_messages WHERE session_id = ? ORDER BY turn_index ASC, created_at ASC, rowid ASC", (session_id,)).fetchall()
        return [ConversationMessage.model_validate_json(row["data"]) for row in rows]

    def list_events_for_run(self, run_id: str) -> list[ExecutionEvent]:
        rows = self.conn.execute("SELECT data FROM events WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)).fetchall()
        return [ExecutionEvent.model_validate_json(row["data"]) for row in rows]

    def list_steps_for_run(self, run_id: str) -> list[RunStep]:
        rows = self.conn.execute("SELECT data FROM run_steps WHERE run_id = ? ORDER BY step_index ASC", (run_id,)).fetchall()
        return [RunStep.model_validate_json(row["data"]) for row in rows]

    def list_context_for_run(self, run_id: str) -> list[ContextArtifact]:
        rows = self.conn.execute("SELECT data FROM context_artifacts WHERE run_id = ? ORDER BY rowid ASC", (run_id,)).fetchall()
        return [ContextArtifact.model_validate_json(row["data"]) for row in rows]

    def list_open_approval_requests(self) -> list[ApprovalRequest]:
        rows = self.conn.execute("SELECT data FROM approval_requests ORDER BY rowid ASC").fetchall()
        requests = [ApprovalRequest.model_validate_json(row["data"]) for row in rows]
        return [request for request in requests if request.status == "open"]

    def get_approval_request(self, approval_request_id: str) -> ApprovalRequest | None:
        row = self.conn.execute("SELECT data FROM approval_requests WHERE approval_request_id = ?", (approval_request_id,)).fetchone()
        return ApprovalRequest.model_validate_json(row["data"]) if row else None

    def get_tool_invocation(self, tool_invocation_id: str) -> ToolInvocation | None:
        row = self.conn.execute("SELECT data FROM tool_invocations WHERE tool_invocation_id = ?", (tool_invocation_id,)).fetchone()
        return ToolInvocation.model_validate_json(row["data"]) if row else None

    def list_tool_invocations_for_run(self, run_id: str) -> list[ToolInvocation]:
        rows = self.conn.execute("SELECT data FROM tool_invocations WHERE run_id = ? ORDER BY rowid ASC", (run_id,)).fetchall()
        return [ToolInvocation.model_validate_json(row["data"]) for row in rows]

    def get_latest_step_for_run(self, run_id: str) -> RunStep | None:
        row = self.conn.execute("SELECT data FROM run_steps WHERE run_id = ? ORDER BY step_index DESC LIMIT 1", (run_id,)).fetchone()
        return RunStep.model_validate_json(row["data"]) if row else None

    def get_run(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT data FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return Run.model_validate_json(row["data"]) if row else None

    def get_task(self, task_id: str) -> Task | None:
        row = self.conn.execute("SELECT data FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return Task.model_validate_json(row["data"]) if row else None

    def get_managed_process(self, process_id: str) -> ManagedProcess | None:
        row = self.conn.execute("SELECT data FROM managed_processes WHERE process_id = ?", (process_id,)).fetchone()
        return ManagedProcess.model_validate_json(row["data"]) if row else None

    def get_session(self, session_id: str) -> ConversationSession | None:
        row = self.conn.execute("SELECT data FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return ConversationSession.model_validate_json(row["data"]) if row else None

    def delete_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        if session is None:
            return
        run_id = session.conversation_id
        self.conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        self.conn.execute("DELETE FROM context_artifacts WHERE run_id = ?", (run_id,))
        self.conn.execute("DELETE FROM tool_invocations WHERE run_id = ?", (run_id,))
        approval_rows = self.conn.execute("SELECT approval_request_id FROM approval_requests WHERE run_id = ?", (run_id,)).fetchall()
        for row in approval_rows:
            self.conn.execute("DELETE FROM approval_decisions WHERE approval_request_id = ?", (row["approval_request_id"],))
        self.conn.execute("DELETE FROM approval_requests WHERE run_id = ?", (run_id,))
        self.conn.commit()

    def delete_all_sessions(self) -> None:
        """Delete all session-history state, including detached run-scoped leftovers.

        Why this is broader than iterating current sessions:
        - older stores or interrupted flows may leave run-scoped records that no
          longer have a surviving row in `sessions`
        - users expect "clear all sessions" to remove transcript/history state
          completely, not only rows still reachable from current session ids

        Intentionally preserved:
        - tasks / runs / run_steps tables are left untouched for now because they
          are not part of the current SessionManager-backed chat history surface
        - managed_processes are left untouched because process-runtime cleanup is
          a separate lifecycle concern
        """
        self.conn.execute("DELETE FROM session_messages")
        self.conn.execute("DELETE FROM sessions")
        self.conn.execute("DELETE FROM events")
        self.conn.execute("DELETE FROM context_artifacts")
        self.conn.execute("DELETE FROM tool_invocations")
        self.conn.execute("DELETE FROM approval_decisions")
        self.conn.execute("DELETE FROM approval_requests")
        self.conn.commit()
