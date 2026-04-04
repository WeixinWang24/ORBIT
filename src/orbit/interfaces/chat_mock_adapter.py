"""Mock chat/session adapter for ORBIT interactive workbench development."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from .adapter_protocol import RuntimeCliAdapter
from .contracts import InterfaceApproval, InterfaceEvent, InterfaceMessage, InterfaceSession
from .mock_adapter import MockOrbitInterfaceAdapter


class MockOrbitChatAdapter(MockOrbitInterfaceAdapter, RuntimeCliAdapter):
    """Add a simple interactive session loop on top of the mock interface data."""

    def create_session(self, *, backend_name: str = "mock-backend", model: str = "dummy-runtime") -> InterfaceSession:
        now = datetime.now(timezone.utc)
        session_id = f"session_live_{len(self._sessions) + 1:03d}"
        conversation_id = f"conversation_live_{len(self._sessions) + 1:03d}"
        session = InterfaceSession(
            session_id=session_id,
            conversation_id=conversation_id,
            backend_name=backend_name,
            model=model,
            updated_at=now,
            message_count=0,
            last_message_preview="",
            status="active",
        )
        self._sessions.insert(0, session)
        self._messages[session_id] = []
        self._events[session_id] = []
        self._artifacts[session_id] = []
        self._tool_calls[session_id] = []
        return session

    def attach_session(self, session_id: str) -> InterfaceSession | None:
        return self.get_session(session_id)

    def send_user_message(self, session_id: str, text: str) -> list[InterfaceMessage]:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        now = datetime.now(timezone.utc)
        transcript = self._messages.setdefault(session_id, [])
        user_message = InterfaceMessage(
            session_id=session_id,
            role="user",
            content=text,
            turn_index=len(transcript) + 1,
            created_at=now,
        )
        transcript.append(user_message)
        self._events.setdefault(session_id, []).append(
            InterfaceEvent(
                session_id=session_id,
                event_type="user_message_received",
                timestamp=now,
                payload={"chars": len(text)},
            )
        )
        assistant_text = self._build_dummy_reply(text)
        assistant_message = InterfaceMessage(
            session_id=session_id,
            role="assistant",
            content=assistant_text,
            turn_index=len(transcript) + 1,
            created_at=now,
        )
        transcript.append(assistant_message)
        self._events.setdefault(session_id, []).append(
            InterfaceEvent(
                session_id=session_id,
                event_type="assistant_message_emitted",
                timestamp=now,
                payload={"mode": "dummy_runtime"},
            )
        )
        session.updated_at = now
        session.message_count = len(transcript)
        session.last_message_preview = assistant_text[:120]
        session.status = "active"
        return [user_message, assistant_message]

    def append_system_message(self, session_id: str, text: str, *, kind: str = "system") -> InterfaceMessage:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        now = datetime.now(timezone.utc)
        transcript = self._messages.setdefault(session_id, [])
        message = InterfaceMessage(
            session_id=session_id,
            role="system",
            content=text,
            turn_index=len(transcript) + 1,
            created_at=now,
            message_kind=kind,
        )
        transcript.append(message)
        session.updated_at = now
        session.message_count = len(transcript)
        session.last_message_preview = text[:120]
        return message

    def slash_help_text(self) -> str:
        return "Available slash commands: /help /new /sessions /attach <session_id> /inspect /chat /approvals /events /tools /artifacts /status /pending /approve /reject"

    def slash_help_page(self) -> str:
        return "\n".join([
            "ORBIT Slash Help",
            "",
            "Default behavior",
            "- Plain text input goes to Agent Runtime chat.",
            "- Slash input routes to CLI/workbench modules.",
            "",
            "Commands",
            "/help                Show this help page",
            "/new                 Create a new session",
            "/sessions            Show stored sessions",
            "/attach <session_id> Attach to an existing session",
            "/chat                Return to Agent Runtime chat",
            "/inspect             Open inspector transcript tab",
            "/events              Open inspector events tab",
            "/tools               Open inspector tool-calls tab",
            "/artifacts           Open inspector artifacts tab",
            "/approvals           Open approvals module",
            "/status              Show current workbench/runtime status",
            "/pending             Show pending approval for current session",
            "/approve [note]      Approve current pending approval",
            "/reject [note]       Reject current pending approval",
            "",
            "Modes",
            "- INSERT: type freely, Enter submits, Esc switches to NAV.",
            "- NAV: q quit, e edit, j/k move, t switch inspector tab.",
            "",
            "Current stage",
            "- Runtime loop is still dummy-backed.",
            "- Real SessionManager integration is the next later phase.",
        ])

    def get_pending_approval(self, session_id: str) -> InterfaceApproval | None:
        return next((approval for approval in self.list_open_approvals() if approval.session_id == session_id), None)

    def resolve_pending_approval(self, session_id: str, decision: str, note: str | None = None) -> dict:
        approval = self.get_pending_approval(session_id)
        if approval is None:
            return {"ok": False, "decision": decision, "note": note, "reason": "no_pending_approval"}
        approval.status = "approved" if decision == "approve" else "rejected"
        summary = f"Approval {approval.status} for {approval.tool_name}."
        if note:
            summary += f" Note: {note}"
        self.append_system_message(session_id, summary, kind="approval_decision")
        self._approvals = [item for item in self._approvals if item.approval_request_id != approval.approval_request_id]
        return {"ok": True, "decision": decision, "note": note, "approval_request_id": approval.approval_request_id}

    def get_session_state_payload(self, session_id: str) -> dict | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        return {
            "session_id": session.session_id,
            "conversation_id": session.conversation_id,
            "backend_name": session.backend_name,
            "model": session.model,
            "message_count": session.message_count,
            "last_message_preview": session.last_message_preview,
            "status": session.status,
        }

    def clear_session(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        self._sessions = [item for item in self._sessions if item.session_id != session_id]
        self._messages.pop(session_id, None)
        self._events.pop(session_id, None)
        self._artifacts.pop(session_id, None)
        self._tool_calls.pop(session_id, None)
        self._approvals = [item for item in self._approvals if item.session_id != session_id]
        return True

    def clear_all_sessions(self) -> bool:
        self._sessions = []
        self._messages = {}
        self._events = {}
        self._artifacts = {}
        self._tool_calls = {}
        self._approvals = []
        return True

    def _build_dummy_reply(self, text: str) -> str:
        lowered = text.lower()
        if "tool" in lowered:
            return "Dummy runtime reply: tool-aware path noted, but this build still returns a mock assistant response."
        if "approval" in lowered:
            return "Dummy runtime reply: approval-relevant intent noticed; real approval round-trip is not wired yet in chat mode."
        return f"Dummy runtime reply: received your input -> {text}"
