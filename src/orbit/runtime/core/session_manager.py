"""Session manager for ORBIT's first multi-turn non-tool/tool conversation paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.store.base import OrbitStore
from orbit.tools.base import ToolResult
from orbit.tools.registry import ToolRegistry


class SessionManager:
    """Manage linear conversation sessions for ORBIT."""

    def __init__(self, *, store: OrbitStore, backend, workspace_root: str):
        self.store = store
        self.backend = backend
        self.workspace_root = workspace_root
        self.tool_registry = ToolRegistry(Path(workspace_root))

    def create_session(self, *, backend_name: str, model: str, conversation_id: str | None = None) -> ConversationSession:
        session = ConversationSession(conversation_id=conversation_id or f"conversation:{backend_name}:{int(datetime.now(timezone.utc).timestamp())}", backend_name=backend_name, model=model)
        self.store.save_session(session)
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        return self.store.get_session(session_id)

    def list_messages(self, session_id: str) -> list[ConversationMessage]:
        return self.store.list_messages_for_session(session_id)

    def append_message(self, *, session_id: str, role: MessageRole, content: str, provider_message_id: str | None = None, metadata: dict | None = None) -> ConversationMessage:
        messages = self.list_messages(session_id)
        message = ConversationMessage(session_id=session_id, role=role, content=content, turn_index=len(messages) + 1, provider_message_id=provider_message_id, metadata=metadata or {})
        self.store.save_message(message)
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)
        return message

    def execute_tool_request(self, *, tool_request: ToolRequest) -> ToolResult:
        """Execute one normalized tool request against the local registry."""
        tool = self.tool_registry.get(tool_request.tool_name)
        return tool.invoke(**tool_request.input_payload)

    def append_tool_result_message(self, *, session_id: str, tool_request: ToolRequest, tool_result: ToolResult) -> ConversationMessage:
        """Append a simple transcript-visible tool result message."""
        if tool_result.ok:
            content = f"Tool result from {tool_request.tool_name}:\n{tool_result.content}"
        else:
            content = f"Tool result from {tool_request.tool_name} (error):\n{tool_result.content}"
        return self.append_message(
            session_id=session_id,
            role=MessageRole.USER,
            content=content,
            metadata={
                "message_kind": "tool_result",
                "tool_name": tool_request.tool_name,
                "tool_ok": tool_result.ok,
                "side_effect_class": tool_request.side_effect_class,
                "tool_data": tool_result.data or {},
            },
        )

    def run_session_turn(self, *, session_id: str, user_input: str) -> ExecutionPlan:
        """Execute one session turn with the first governed tool closure path."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        self.append_message(session_id=session_id, role=MessageRole.USER, content=user_input)
        messages = self.list_messages(session_id)
        plan = self._plan_from_messages(session=session, messages=messages)

        if plan.tool_request is None:
            if plan.final_text:
                self.append_message(session_id=session_id, role=MessageRole.ASSISTANT, content=plan.final_text, metadata={"source_backend": plan.source_backend, "plan_label": plan.plan_label})
            return plan

        if plan.tool_request.requires_approval:
            return plan

        tool_result = self.execute_tool_request(tool_request=plan.tool_request)
        self.append_tool_result_message(session_id=session_id, tool_request=plan.tool_request, tool_result=tool_result)
        updated_messages = self.list_messages(session_id)
        final_plan = self._plan_from_messages(session=session, messages=updated_messages)
        if final_plan.final_text:
            self.append_message(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=final_plan.final_text,
                metadata={
                    "source_backend": final_plan.source_backend,
                    "plan_label": final_plan.plan_label,
                    "continued_after_tool": True,
                    "tool_name": plan.tool_request.tool_name,
                    "tool_ok": tool_result.ok,
                },
            )
        return final_plan

    def _plan_from_messages(self, *, session: ConversationSession, messages: list[ConversationMessage]) -> ExecutionPlan:
        """Use history-aware provider path when available, otherwise fallback."""
        if hasattr(self.backend, "plan_from_messages"):
            return self.backend.plan_from_messages(messages, session=session)
        latest_user = next((message for message in reversed(messages) if message.role == MessageRole.USER), None)
        if latest_user is None:
            raise ValueError("cannot fallback to descriptor path without a user message")
        descriptor = RunDescriptor(
            session_key=f"session:{session.session_id}",
            conversation_id=session.conversation_id,
            workspace=WorkspaceDescriptor(cwd=self.workspace_root, writable_roots=[self.workspace_root]),
            user_input=latest_user.content,
        )
        return self.backend.plan(descriptor)
