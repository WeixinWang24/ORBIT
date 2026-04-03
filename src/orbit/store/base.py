"""Persistence interfaces for ORBIT runtime state.

This module defines the stable store boundary used by runtime, CLI, and notebook
projection code. The goal is to preserve core domain object stability while
allowing the underlying persistence implementation to change.

Architectural note:
- PostgreSQL is the intended primary persistence direction for ORBIT.
- SQLite remains available as a temporary bootstrap implementation for local
  bring-up and low-friction experimentation.
- Runtime code should depend on this interface rather than a specific backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orbit.models import (
    ApprovalDecision,
    ApprovalRequest,
    ContextArtifact,
    ConversationMessage,
    ConversationSession,
    ExecutionEvent,
    Run,
    RunStep,
    Task,
    ToolInvocation,
)


class OrbitStore(ABC):
    """Abstract persistence boundary for ORBIT domain objects."""

    @abstractmethod
    def save_task(self, task: Task) -> None:
        """Persist a task record."""

    @abstractmethod
    def save_run(self, run: Run) -> None:
        """Persist a run record."""

    @abstractmethod
    def save_step(self, step: RunStep) -> None:
        """Persist a run step record."""

    @abstractmethod
    def save_event(self, event: ExecutionEvent) -> None:
        """Persist an execution event record."""

    @abstractmethod
    def save_tool_invocation(self, tool: ToolInvocation) -> None:
        """Persist a tool invocation record."""

    @abstractmethod
    def save_approval_request(self, request: ApprovalRequest) -> None:
        """Persist an approval request record."""

    @abstractmethod
    def save_approval_decision(self, decision: ApprovalDecision) -> None:
        """Persist an approval decision record."""

    @abstractmethod
    def save_context_artifact(self, artifact: ContextArtifact) -> None:
        """Persist a run-scoped context artifact."""

    @abstractmethod
    def save_session(self, session: ConversationSession) -> None:
        """Persist a conversation session record."""

    @abstractmethod
    def save_message(self, message: ConversationMessage) -> None:
        """Persist a conversation message record."""

    @abstractmethod
    def list_tasks(self) -> list[Task]:
        """Return persisted tasks in a stable listing order."""

    @abstractmethod
    def list_runs(self) -> list[Run]:
        """Return persisted runs in a stable listing order."""

    @abstractmethod
    def list_sessions(self) -> list[ConversationSession]:
        """Return persisted sessions in a stable listing order."""

    @abstractmethod
    def list_messages_for_session(self, session_id: str) -> list[ConversationMessage]:
        """Return messages for a session in stable chronological order."""

    @abstractmethod
    def list_events_for_run(self, run_id: str) -> list[ExecutionEvent]:
        """Return execution events for a run in stable chronological order."""

    @abstractmethod
    def list_steps_for_run(self, run_id: str) -> list[RunStep]:
        """Return run steps for a run in stable execution order."""

    @abstractmethod
    def list_context_for_run(self, run_id: str) -> list[ContextArtifact]:
        """Return context artifacts associated with a run."""

    @abstractmethod
    def list_open_approval_requests(self) -> list[ApprovalRequest]:
        """Return currently open approval requests across runs."""

    @abstractmethod
    def get_approval_request(self, approval_request_id: str) -> ApprovalRequest | None:
        """Return an approval request by id, or None if it does not exist."""

    @abstractmethod
    def get_tool_invocation(self, tool_invocation_id: str) -> ToolInvocation | None:
        """Return a tool invocation by id, or None if it does not exist."""

    @abstractmethod
    def list_tool_invocations_for_run(self, run_id: str) -> list[ToolInvocation]:
        """Return tool invocations associated with a run in stable order."""

    @abstractmethod
    def get_latest_step_for_run(self, run_id: str) -> RunStep | None:
        """Return the latest step for a run based on stable execution ordering."""

    @abstractmethod
    def get_run(self, run_id: str) -> Run | None:
        """Return a run by id, or None if it does not exist."""

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None:
        """Return a task by id, or None if it does not exist."""

    @abstractmethod
    def get_session(self, session_id: str) -> ConversationSession | None:
        """Return a session by id, or None if it does not exist."""
