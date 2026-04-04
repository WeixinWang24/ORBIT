"""Mock chat/session adapter for ORBIT interactive workbench development."""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import InterfaceEvent, InterfaceMessage, InterfaceSession
from .mock_adapter import MockOrbitInterfaceAdapter


class MockOrbitChatAdapter(MockOrbitInterfaceAdapter):
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

    def _build_dummy_reply(self, text: str) -> str:
        lowered = text.lower()
        if "tool" in lowered:
            return "Dummy runtime reply: tool-aware path noted, but this build still returns a mock assistant response."
        if "approval" in lowered:
            return "Dummy runtime reply: approval-relevant intent noticed; real approval round-trip is not wired yet in chat mode."
        return f"Dummy runtime reply: received your input -> {text}"
