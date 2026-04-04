"""Mock adapter for isolated ORBIT interface development."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .contracts import (
    InterfaceApproval,
    InterfaceArtifact,
    InterfaceEvent,
    InterfaceMessage,
    InterfaceSession,
    InterfaceToolCall,
)


class MockOrbitInterfaceAdapter:
    """Provide deterministic mock data for interface-only development.

    This adapter intentionally avoids runtime coupling so Web UI and CLI work
    can proceed while kernel/runtime work is happening in parallel.
    """

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._sessions = [
            InterfaceSession(
                session_id="session_demo_alpha",
                conversation_id="conversation_demo_alpha",
                backend_name="openai-codex",
                model="gpt-5.4",
                updated_at=now - timedelta(minutes=3),
                message_count=6,
                last_message_preview="Workflow calling should preserve host-owned projection boundaries.",
                status="active",
            ),
            InterfaceSession(
                session_id="session_demo_beta",
                conversation_id="conversation_demo_beta",
                backend_name="mock-backend",
                model="dummy-runtime",
                updated_at=now - timedelta(minutes=28),
                message_count=4,
                last_message_preview="Approval required before executing replace_in_file.",
                status="waiting_for_approval",
            ),
        ]
        self._messages = {
            "session_demo_alpha": [
                InterfaceMessage(session_id="session_demo_alpha", role="user", content="Summarize the current workflow-calling boundary.", turn_index=1, created_at=now - timedelta(minutes=12)),
                InterfaceMessage(session_id="session_demo_alpha", role="assistant", content="Workflow calling should remain a bounded soft process call.", turn_index=2, created_at=now - timedelta(minutes=11)),
                InterfaceMessage(session_id="session_demo_alpha", role="user", content="What must stay outside the child runtime?", turn_index=3, created_at=now - timedelta(minutes=8)),
                InterfaceMessage(session_id="session_demo_alpha", role="assistant", content="Selection authority, binding authority, and projection authority remain outside.", turn_index=4, created_at=now - timedelta(minutes=7)),
                InterfaceMessage(session_id="session_demo_alpha", role="tool", content="Tool result from read_file: workflow-calling-boundary-preservation-synthesis loaded.", turn_index=5, created_at=now - timedelta(minutes=5), message_kind="tool_result", metadata={"tool_name": "read_file", "tool_ok": True}),
                InterfaceMessage(session_id="session_demo_alpha", role="assistant", content="Workflow calling should preserve host-owned projection boundaries.", turn_index=6, created_at=now - timedelta(minutes=3)),
            ],
            "session_demo_beta": [
                InterfaceMessage(session_id="session_demo_beta", role="user", content="Replace the old term with the new one in the draft note.", turn_index=1, created_at=now - timedelta(minutes=40)),
                InterfaceMessage(session_id="session_demo_beta", role="assistant", content="I can do that, but this path needs approval first.", turn_index=2, created_at=now - timedelta(minutes=39)),
                InterfaceMessage(session_id="session_demo_beta", role="assistant", content="Approval required before executing replace_in_file (side_effect_class=write).", turn_index=3, created_at=now - timedelta(minutes=38), message_kind="approval_request", metadata={"tool_name": "replace_in_file"}),
                InterfaceMessage(session_id="session_demo_beta", role="assistant", content="Waiting for approval.", turn_index=4, created_at=now - timedelta(minutes=28)),
            ],
        }
        self._events = {
            "session_demo_alpha": [
                InterfaceEvent(session_id="session_demo_alpha", event_type="run_started", timestamp=now - timedelta(minutes=12), payload={"mode": "session_turn"}),
                InterfaceEvent(session_id="session_demo_alpha", event_type="tool_invocation_completed", timestamp=now - timedelta(minutes=5), payload={"tool_name": "read_file", "ok": True}),
            ],
            "session_demo_beta": [
                InterfaceEvent(session_id="session_demo_beta", event_type="run_started", timestamp=now - timedelta(minutes=40), payload={"mode": "session_turn"}),
                InterfaceEvent(session_id="session_demo_beta", event_type="approval_requested", timestamp=now - timedelta(minutes=38), payload={"tool_name": "replace_in_file"}),
            ],
        }
        self._artifacts = {
            "session_demo_alpha": [
                InterfaceArtifact(session_id="session_demo_alpha", artifact_type="session_context_assembly", source="context_assembly", content='{"assembly_version": "mock-v1"}'),
            ],
            "session_demo_beta": [
                InterfaceArtifact(session_id="session_demo_beta", artifact_type="session_policy_decision", source="governance", content="approval_required=true"),
            ],
        }
        self._tool_calls = {
            "session_demo_alpha": [
                InterfaceToolCall(session_id="session_demo_alpha", tool_name="read_file", status="completed", side_effect_class="safe", requires_approval=False, summary="Loaded workflow-calling synthesis note.", payload={"path": "docs/workflow-calling-boundary-preservation-synthesis.md"}),
            ],
            "session_demo_beta": [
                InterfaceToolCall(session_id="session_demo_beta", tool_name="replace_in_file", status="pending_approval", side_effect_class="write", requires_approval=True, summary="Requested controlled text mutation.", payload={"path": "notes/draft.md"}),
            ],
        }
        self._approvals = [
            InterfaceApproval(
                approval_request_id="approval_demo_001",
                session_id="session_demo_beta",
                tool_name="replace_in_file",
                side_effect_class="write",
                status="pending",
                summary="Replace old terminology in draft note.",
                opened_at=now - timedelta(minutes=38),
                payload={"path": "notes/draft.md"},
            )
        ]

    def list_sessions(self) -> list[InterfaceSession]:
        return list(self._sessions)

    def get_session(self, session_id: str) -> InterfaceSession | None:
        return next((session for session in self._sessions if session.session_id == session_id), None)

    def list_messages(self, session_id: str) -> list[InterfaceMessage]:
        return list(self._messages.get(session_id, []))

    def list_events(self, session_id: str) -> list[InterfaceEvent]:
        return list(self._events.get(session_id, []))

    def list_artifacts(self, session_id: str) -> list[InterfaceArtifact]:
        return list(self._artifacts.get(session_id, []))

    def list_tool_calls(self, session_id: str) -> list[InterfaceToolCall]:
        return list(self._tool_calls.get(session_id, []))

    def list_open_approvals(self) -> list[InterfaceApproval]:
        return list(self._approvals)
