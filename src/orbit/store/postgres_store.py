"""PostgreSQL-backed store for ORBIT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from psycopg2.extensions import connection as PGConnection

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

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ NULL, ended_at TIMESTAMPTZ NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS run_steps (step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_type TEXT NOT NULL, status TEXT NOT NULL, started_at TIMESTAMPTZ NULL, ended_at TIMESTAMPTZ NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NULL, event_type TEXT NOT NULL, timestamp TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS tool_invocations (tool_invocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL, tool_name TEXT NOT NULL, status TEXT NOT NULL, requested_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ NULL, ended_at TIMESTAMPTZ NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS approval_requests (approval_request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS approval_decisions (approval_decision_id TEXT PRIMARY KEY, approval_request_id TEXT NOT NULL, decided_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS context_artifacts (context_artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, artifact_type TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, backend_name TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS managed_processes (process_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS session_messages (message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, turn_index INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL);
CREATE INDEX IF NOT EXISTS idx_runs_task_id ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_run_steps_run_id_step_index ON run_steps(run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_events_run_id_timestamp ON events(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_run_id ON tool_invocations(run_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_run_id ON approval_requests(run_id);
CREATE INDEX IF NOT EXISTS idx_context_artifacts_run_id ON context_artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_managed_processes_session_updated_at ON managed_processes(session_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_session_messages_session_turn ON session_messages(session_id, turn_index, created_at);
"""


@dataclass
class PostgresConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "orbit"
    user: str = "orbit"
    password: str = "orbit"


class PostgresStore(OrbitStore):
    """PostgreSQL implementation of the ORBIT persistence boundary."""

    def __init__(self, config: PostgresConfig):
        self.config = config
        self.conn: PGConnection = psycopg2.connect(host=config.host, port=config.port, dbname=config.dbname, user=config.user, password=config.password)
        self.conn.autocommit = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        self.conn.commit()

    @staticmethod
    def _payload(model: Any) -> Json:
        return Json(model.model_dump(mode="json"))

    @staticmethod
    def _read_model(model_cls, row: dict[str, Any]) -> Any:
        return model_cls.model_validate(row["data"])

    def save_task(self, task: Task) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO tasks (task_id, created_at, data) VALUES (%s, %s, %s) ON CONFLICT (task_id) DO UPDATE SET created_at = EXCLUDED.created_at, data = EXCLUDED.data", (task.task_id, task.created_at, self._payload(task)))
        self.conn.commit()

    def save_run(self, run: Run) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO runs (run_id, task_id, status, created_at, started_at, ended_at, data) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (run_id) DO UPDATE SET task_id = EXCLUDED.task_id, status = EXCLUDED.status, created_at = EXCLUDED.created_at, started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at, data = EXCLUDED.data", (run.run_id, run.task_id, run.status, run.created_at, run.started_at, run.ended_at, self._payload(run)))
        self.conn.commit()

    def save_step(self, step: RunStep) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO run_steps (step_id, run_id, step_index, step_type, status, started_at, ended_at, data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (step_id) DO UPDATE SET run_id = EXCLUDED.run_id, step_index = EXCLUDED.step_index, step_type = EXCLUDED.step_type, status = EXCLUDED.status, started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at, data = EXCLUDED.data", (step.step_id, step.run_id, step.index, step.step_type, step.status, step.started_at, step.ended_at, self._payload(step)))
        self.conn.commit()

    def save_event(self, event: ExecutionEvent) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO events (event_id, run_id, step_id, event_type, timestamp, data) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO UPDATE SET run_id = EXCLUDED.run_id, step_id = EXCLUDED.step_id, event_type = EXCLUDED.event_type, timestamp = EXCLUDED.timestamp, data = EXCLUDED.data", (event.event_id, event.run_id, event.step_id, event.event_type, event.timestamp, self._payload(event)))
        self.conn.commit()

    def save_tool_invocation(self, tool: ToolInvocation) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO tool_invocations (tool_invocation_id, run_id, step_id, tool_name, status, requested_at, started_at, ended_at, data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tool_invocation_id) DO UPDATE SET run_id = EXCLUDED.run_id, step_id = EXCLUDED.step_id, tool_name = EXCLUDED.tool_name, status = EXCLUDED.status, requested_at = EXCLUDED.requested_at, started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at, data = EXCLUDED.data", (tool.tool_invocation_id, tool.run_id, tool.step_id, tool.tool_name, tool.status, tool.requested_at, tool.started_at, tool.ended_at, self._payload(tool)))
        self.conn.commit()

    def save_approval_request(self, request: ApprovalRequest) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO approval_requests (approval_request_id, run_id, step_id, target_type, target_id, status, created_at, data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (approval_request_id) DO UPDATE SET run_id = EXCLUDED.run_id, step_id = EXCLUDED.step_id, target_type = EXCLUDED.target_type, target_id = EXCLUDED.target_id, status = EXCLUDED.status, created_at = EXCLUDED.created_at, data = EXCLUDED.data", (request.approval_request_id, request.run_id, request.step_id, request.target_type, request.target_id, request.status, request.created_at, self._payload(request)))
        self.conn.commit()

    def save_approval_decision(self, decision: ApprovalDecision) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO approval_decisions (approval_decision_id, approval_request_id, decided_at, data) VALUES (%s, %s, %s, %s) ON CONFLICT (approval_decision_id) DO UPDATE SET approval_request_id = EXCLUDED.approval_request_id, decided_at = EXCLUDED.decided_at, data = EXCLUDED.data", (decision.approval_decision_id, decision.approval_request_id, decision.decided_at, self._payload(decision)))
        self.conn.commit()

    def save_context_artifact(self, artifact: ContextArtifact) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO context_artifacts (context_artifact_id, run_id, artifact_type, created_at, data) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (context_artifact_id) DO UPDATE SET run_id = EXCLUDED.run_id, artifact_type = EXCLUDED.artifact_type, created_at = EXCLUDED.created_at, data = EXCLUDED.data", (artifact.context_artifact_id, artifact.run_id, artifact.artifact_type, artifact.created_at, self._payload(artifact)))
        self.conn.commit()

    def save_session(self, session: ConversationSession) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO sessions (session_id, conversation_id, backend_name, model, status, created_at, updated_at, data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (session_id) DO UPDATE SET conversation_id = EXCLUDED.conversation_id, backend_name = EXCLUDED.backend_name, model = EXCLUDED.model, status = EXCLUDED.status, created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at, data = EXCLUDED.data", (session.session_id, session.conversation_id, session.backend_name, session.model, session.status, session.created_at, session.updated_at, self._payload(session)))
        self.conn.commit()

    def save_managed_process(self, process: ManagedProcess) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO managed_processes (process_id, session_id, status, updated_at, data) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (process_id) DO UPDATE SET session_id = EXCLUDED.session_id, status = EXCLUDED.status, updated_at = EXCLUDED.updated_at, data = EXCLUDED.data",
                (process.process_id, process.session_id, process.status, process.updated_at, self._payload(process)),
            )
        self.conn.commit()

    def save_message(self, message: ConversationMessage) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO session_messages (message_id, session_id, role, turn_index, created_at, data) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET session_id = EXCLUDED.session_id, role = EXCLUDED.role, turn_index = EXCLUDED.turn_index, created_at = EXCLUDED.created_at, data = EXCLUDED.data", (message.message_id, message.session_id, message.role, message.turn_index, message.created_at, self._payload(message)))
        self.conn.commit()

    def list_tasks(self) -> list[Task]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM tasks ORDER BY created_at ASC")
            return [self._read_model(Task, row) for row in cur.fetchall()]

    def list_runs(self) -> list[Run]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM runs ORDER BY created_at ASC")
            return [self._read_model(Run, row) for row in cur.fetchall()]

    def list_sessions(self) -> list[ConversationSession]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM sessions ORDER BY updated_at DESC, created_at DESC")
            return [self._read_model(ConversationSession, row) for row in cur.fetchall()]

    def list_managed_processes(self) -> list[ManagedProcess]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM managed_processes ORDER BY updated_at ASC, process_id ASC")
            return [self._read_model(ManagedProcess, row) for row in cur.fetchall()]

    def list_messages_for_session(self, session_id: str) -> list[ConversationMessage]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM session_messages WHERE session_id = %s ORDER BY turn_index ASC, created_at ASC", (session_id,))
            return [self._read_model(ConversationMessage, row) for row in cur.fetchall()]

    def list_events_for_run(self, run_id: str) -> list[ExecutionEvent]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM events WHERE run_id = %s ORDER BY timestamp ASC", (run_id,))
            return [self._read_model(ExecutionEvent, row) for row in cur.fetchall()]

    def list_steps_for_run(self, run_id: str) -> list[RunStep]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM run_steps WHERE run_id = %s ORDER BY step_index ASC", (run_id,))
            return [self._read_model(RunStep, row) for row in cur.fetchall()]

    def list_context_for_run(self, run_id: str) -> list[ContextArtifact]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM context_artifacts WHERE run_id = %s ORDER BY created_at ASC", (run_id,))
            return [self._read_model(ContextArtifact, row) for row in cur.fetchall()]

    def list_open_approval_requests(self) -> list[ApprovalRequest]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM approval_requests WHERE status = 'open' ORDER BY created_at ASC")
            return [self._read_model(ApprovalRequest, row) for row in cur.fetchall()]

    def get_approval_request(self, approval_request_id: str) -> ApprovalRequest | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM approval_requests WHERE approval_request_id = %s", (approval_request_id,))
            row = cur.fetchone()
            return self._read_model(ApprovalRequest, row) if row else None

    def get_tool_invocation(self, tool_invocation_id: str) -> ToolInvocation | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM tool_invocations WHERE tool_invocation_id = %s", (tool_invocation_id,))
            row = cur.fetchone()
            return self._read_model(ToolInvocation, row) if row else None

    def list_tool_invocations_for_run(self, run_id: str) -> list[ToolInvocation]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM tool_invocations WHERE run_id = %s ORDER BY requested_at ASC, tool_invocation_id ASC", (run_id,))
            return [self._read_model(ToolInvocation, row) for row in cur.fetchall()]

    def get_latest_step_for_run(self, run_id: str) -> RunStep | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM run_steps WHERE run_id = %s ORDER BY step_index DESC LIMIT 1", (run_id,))
            row = cur.fetchone()
            return self._read_model(RunStep, row) if row else None

    def get_run(self, run_id: str) -> Run | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            return self._read_model(Run, row) if row else None

    def get_task(self, task_id: str) -> Task | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM tasks WHERE task_id = %s", (task_id,))
            row = cur.fetchone()
            return self._read_model(Task, row) if row else None

    def get_managed_process(self, process_id: str) -> ManagedProcess | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM managed_processes WHERE process_id = %s", (process_id,))
            row = cur.fetchone()
            return self._read_model(ManagedProcess, row) if row else None

    def get_session(self, session_id: str) -> ConversationSession | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT data FROM sessions WHERE session_id = %s", (session_id,))
            row = cur.fetchone()
            return self._read_model(ConversationSession, row) if row else None

    def delete_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        if session is None:
            return
        run_id = session.conversation_id
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM session_messages WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM managed_processes WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM events WHERE run_id = %s", (run_id,))
            cur.execute("DELETE FROM context_artifacts WHERE run_id = %s", (run_id,))
            cur.execute("DELETE FROM tool_invocations WHERE run_id = %s", (run_id,))
            cur.execute(
                "DELETE FROM approval_decisions WHERE approval_request_id IN (SELECT approval_request_id FROM approval_requests WHERE run_id = %s)",
                (run_id,),
            )
            cur.execute("DELETE FROM approval_requests WHERE run_id = %s", (run_id,))
        self.conn.commit()

    def delete_all_sessions(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM session_messages")
            cur.execute("DELETE FROM managed_processes")
            cur.execute("DELETE FROM sessions")
            cur.execute("DELETE FROM events")
            cur.execute("DELETE FROM context_artifacts")
            cur.execute("DELETE FROM tool_invocations")
            cur.execute("DELETE FROM approval_decisions")
            cur.execute("DELETE FROM approval_requests")
        self.conn.commit()
