"""Runtime adapter for the active runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from orbit.runtime import SessionManager
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.runtime.providers.openai_codex import OpenAICodexConfig, OpenAICodexExecutionBackend
from orbit.settings import DEFAULT_WORKSPACE_ROOT, REPO_ROOT
from orbit.store import create_default_store

from .adapter_protocol import RuntimeCliAdapter
from .contracts import (
    InterfaceApproval,
    InterfaceArtifact,
    InterfaceEvent,
    InterfaceMessage,
    InterfaceSession,
    InterfaceToolCall,
)


@dataclass
class RuntimeAdapterConfig:
    model: str = "gpt-5.4"
    enable_tools: bool = True
    enable_mcp_filesystem: bool = True
    enable_mcp_git: bool = True
    enable_mcp_bash: bool = True
    enable_mcp_process: bool = True


def build_codex_session_manager(*, model: str, enable_tools: bool = False, enable_mcp_filesystem: bool = False, enable_mcp_git: bool = False, enable_mcp_bash: bool = False, enable_mcp_process: bool = False) -> SessionManager:
    backend = OpenAICodexExecutionBackend(
        config=OpenAICodexConfig(model=model, enable_tools=enable_tools),
        repo_root=REPO_ROOT,
        workspace_root=DEFAULT_WORKSPACE_ROOT,
    )
    return SessionManager(
        store=create_default_store(),
        backend=backend,
        workspace_root=str(DEFAULT_WORKSPACE_ROOT),
        enable_mcp_filesystem=enable_mcp_filesystem,
        enable_mcp_git=enable_mcp_git,
        enable_mcp_bash=enable_mcp_bash,
        enable_mcp_process=enable_mcp_process,
    )


def get_pending_session_approval(session_manager: SessionManager, session_id: str) -> dict | None:
    session = session_manager.get_session(session_id)
    if session is None or not isinstance(session.metadata, dict):
        return None
    pending = session.metadata.get("pending_approval")
    return pending if isinstance(pending, dict) else None


def resolve_pending_session_approval(session_manager: SessionManager, session_id: str, decision: str, note: str | None = None):
    pending = get_pending_session_approval(session_manager, session_id)
    if not pending:
        return None
    approval_request_id = pending.get("approval_request_id")
    if not isinstance(approval_request_id, str) or not approval_request_id:
        return None
    return session_manager.resolve_session_approval(
        session_id=session_id,
        approval_request_id=approval_request_id,
        decision=decision,
        note=note,
    )


class SessionManagerRuntimeAdapter(RuntimeCliAdapter):
    """First real runtime adapter skeleton for the new CLI UI.

    The adapter mirrors the capability envelope of `cli_session.py` in a form
    that the PTY workbench can absorb gradually.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self.session_manager = session_manager

    @classmethod
    def build(cls, config: RuntimeAdapterConfig | None = None) -> "SessionManagerRuntimeAdapter":
        config = config or RuntimeAdapterConfig()
        session_manager = build_codex_session_manager(
            model=config.model,
            enable_tools=config.enable_tools,
            enable_mcp_filesystem=config.enable_mcp_filesystem,
            enable_mcp_git=config.enable_mcp_git,
            enable_mcp_bash=config.enable_mcp_bash,
            enable_mcp_process=config.enable_mcp_process,
        )
        return cls(session_manager)

    def create_session(self, *, backend_name: str = "openai-codex", model: str | None = None) -> InterfaceSession:
        session = self.session_manager.create_session(
            backend_name=backend_name,
            model=model or getattr(self.session_manager.backend.config, "model", "gpt-5.4"),
        )
        return self._map_session(session)

    def attach_session(self, session_id: str) -> InterfaceSession | None:
        session = self.session_manager.get_session(session_id)
        return self._map_session(session) if session is not None else None

    def get_session(self, session_id: str) -> InterfaceSession | None:
        session = self.session_manager.get_session(session_id)
        return self._map_session(session) if session is not None else None

    def list_sessions(self) -> list[InterfaceSession]:
        sessions = self.session_manager.store.list_sessions()
        return [self._map_session_summary(session) for session in sessions]

    def list_messages(self, session_id: str) -> list[InterfaceMessage]:
        messages = self.session_manager.list_messages(session_id)
        return [self._map_message(message) for message in messages]

    def list_events(self, session_id: str) -> list[InterfaceEvent]:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return []
        events = self.session_manager.store.list_events_for_run(session.conversation_id)
        return [
            InterfaceEvent(
                session_id=session_id,
                event_type=getattr(event.event_type, "value", str(event.event_type)),
                timestamp=event.timestamp,
                payload=event.payload or {},
            )
            for event in events
        ]

    def list_artifacts(self, session_id: str) -> list[InterfaceArtifact]:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return []
        list_artifacts_fn = getattr(self.session_manager.store, "list_context_artifacts_for_run", None)
        if not callable(list_artifacts_fn):
            return []
        artifacts = list_artifacts_fn(session.conversation_id)
        return [
            InterfaceArtifact(
                session_id=session_id,
                artifact_type=artifact.artifact_type,
                source=artifact.source,
                content=artifact.content,
            )
            for artifact in artifacts
        ]

    def list_tool_calls(self, session_id: str) -> list[InterfaceToolCall]:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return []
        tool_calls = self.session_manager.store.list_tool_invocations_for_run(session.conversation_id)
        return [
            InterfaceToolCall(
                session_id=session_id,
                tool_name=call.tool_name,
                status=getattr(call.status, "value", str(call.status)),
                side_effect_class=getattr(call, "side_effect_class", "safe"),
                requires_approval=bool(getattr(call, "requires_approval", False)),
                summary=self._tool_call_summary(call),
                payload=call.input_payload or {},
            )
            for call in tool_calls
        ]

    def list_open_approvals(self) -> list[InterfaceApproval]:
        approvals = self.session_manager.list_open_session_approvals()
        return [self._map_open_approval(item) for item in approvals]

    def send_user_message(self, session_id: str, text: str, on_assistant_partial_text=None) -> list[InterfaceMessage]:
        self.session_manager.run_session_turn(session_id=session_id, user_input=text, on_assistant_partial_text=on_assistant_partial_text)
        pending = self.get_pending_approval(session_id)
        if pending is not None:
            self.append_system_message(
                session_id,
                (
                    f"Pending approval: {pending.tool_name} "
                    f"(approval_request_id={pending.approval_request_id}, side_effect={pending.side_effect_class}).\n"
                    "Use /approve or /reject in chat, or open the approvals panel and press a/r."
                ),
                kind="approval_guidance",
            )
        return self.list_messages(session_id)

    def append_system_message(self, session_id: str, text: str, *, kind: str = "system") -> InterfaceMessage:
        message = self.session_manager.append_message(
            session_id=session_id,
            role="assistant",
            content=text,
            metadata={"message_kind": kind},
        )
        return self._map_message(message)

    def slash_help_text(self) -> str:
        return (
            "Available slash commands: /help /new /sessions /attach <session_id> "
            "/inspect /chat /approvals /events /tools /artifacts /status /pending /approve /reject"
        )

    def slash_help_page(self) -> str:
        return "\n".join(
            [
                "ORBIT Slash Help",
                "",
                "Slash commands",
                "/help /new /sessions /attach <session_id> /detach",
                "/chat /inspect /events /tools /artifacts /approvals /status",
                "/pending /approve [note] /reject [note]",
                "/show /state /clear /clear-all",
            ]
        )

    def get_workbench_status(self) -> dict[str, Any]:
        sessions = self.list_sessions()
        tool_names = sorted(tool.name for tool in self.session_manager.tool_registry.list_tools())
        return {
            "adapter_kind": "session_manager_runtime",
            "session_count": len(sessions),
            "approval_count": len(self.list_open_approvals()),
            "registered_tool_count": len(tool_names),
            "registered_tool_names": tool_names,
        }

    def get_pending_approval(self, session_id: str) -> InterfaceApproval | None:
        session = self.session_manager.get_session(session_id)
        if session is None or not isinstance(session.metadata, dict):
            return None
        pending = session.metadata.get("pending_approval")
        if not isinstance(pending, dict):
            return None
        return self._map_open_approval({"session_id": session_id, **pending})

    def resolve_pending_approval(self, session_id: str, decision: str, note: str | None = None):
        session = self.session_manager.get_session(session_id)
        if session is None or not isinstance(session.metadata, dict):
            return None
        pending = session.metadata.get("pending_approval")
        if not isinstance(pending, dict):
            return None
        approval_request_id = pending.get("approval_request_id")
        if not isinstance(approval_request_id, str) or not approval_request_id:
            return None
        return self.session_manager.resolve_session_approval(
            session_id=session_id,
            approval_request_id=approval_request_id,
            decision=decision,
            note=note,
        )

    def get_session_state_payload(self, session_id: str) -> dict[str, Any] | None:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return None
        return session.model_dump(mode="json")

    def clear_session(self, session_id: str) -> bool:
        delete_fn = getattr(self.session_manager.store, "delete_session", None)
        if not callable(delete_fn):
            return False
        delete_fn(session_id)
        return True

    def clear_all_sessions(self) -> bool:
        delete_all_fn = getattr(self.session_manager.store, "delete_all_sessions", None)
        if not callable(delete_all_fn):
            return False
        delete_all_fn()
        return True

    def _map_session_summary(self, session) -> InterfaceSession:
        return InterfaceSession(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            backend_name=session.backend_name,
            model=session.model,
            updated_at=session.updated_at,
            message_count=0,
            last_message_preview="",
            status="active",
        )

    def _map_session(self, session) -> InterfaceSession:
        messages = self.session_manager.list_messages(session.session_id)
        last_message = messages[-1].content if messages else ""
        pending = self.get_pending_approval(session.session_id)
        status = "waiting_for_approval" if pending is not None else "active"
        return InterfaceSession(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            backend_name=session.backend_name,
            model=session.model,
            updated_at=session.updated_at,
            message_count=len(messages),
            last_message_preview=last_message[:120],
            status=status,
        )

    def _map_message(self, message) -> InterfaceMessage:
        role = getattr(message.role, "value", str(message.role))
        return InterfaceMessage(
            session_id=message.session_id,
            role=role,
            content=message.content,
            turn_index=message.turn_index,
            created_at=message.created_at,
            message_kind=message.metadata.get("message_kind") if isinstance(message.metadata, dict) else None,
            metadata=message.metadata or {},
        )

    def _tool_call_summary(self, call) -> str:
        payload = call.input_payload or {}
        if payload:
            first_key = next(iter(payload.keys()))
            return f"{call.tool_name} with {first_key}"
        return call.tool_name

    def _map_open_approval(self, item: dict[str, Any]) -> InterfaceApproval:
        tool_request = item.get("tool_request") if isinstance(item.get("tool_request"), dict) else {}
        payload = tool_request.get("input_payload", {}) if isinstance(tool_request, dict) else {}
        return InterfaceApproval(
            approval_request_id=str(item.get("approval_request_id") or "unknown-approval"),
            session_id=str(item.get("session_id") or "unknown-session"),
            tool_name=str(tool_request.get("tool_name") or "unknown_tool"),
            side_effect_class=str(tool_request.get("side_effect_class") or "safe"),
            status="pending",
            summary=f"Approval required before executing {tool_request.get('tool_name', 'unknown_tool')}.",
            payload=payload if isinstance(payload, dict) else {},
        )
