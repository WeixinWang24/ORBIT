"""Session manager for ORBIT's first multi-turn non-tool/tool conversation paths."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orbit.models import ContextArtifact, ConversationMessage, ConversationSession, ExecutionEvent, GovernedToolState, MessageRole, ToolInvocation, ToolInvocationStatus
from orbit.models.core import new_id
from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.core.events import RuntimeEventType
from orbit.runtime.execution.continuation_context import build_rejection_continuation_context
from orbit.runtime.memory_service import MemoryService
from orbit.runtime.governance.tool_approval_policy import PolicyDecision, PolicyEvaluationInput, evaluate_tool_approval_policy
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_server, bootstrap_local_git_mcp_server
from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
from orbit.runtime.mcp.governance import resolve_filesystem_mcp_target_path
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.store.base import OrbitStore
from orbit.tools.base import ToolResult
from orbit.tools.registry import ToolRegistry


class SessionManager:
    """Manage linear conversation sessions for ORBIT.

    Current MVP single-turn contract:
    - ``run_session_turn(...)`` is the canonical first-turn executor
    - plain-text turns complete inside ``run_session_turn(...)``
    - non-approval tool turns also complete inside ``run_session_turn(...)``
      through one bounded governed tool closure
    - approval-gated tool turns stop at a persisted waiting boundary and must
      resume through ``resolve_session_approval(...)``

    The approval path is intentionally lightweight and session-local in this
    phase rather than a full reuse of run-oriented approval persistence.
    """

    def __init__(
        self,
        *,
        store: OrbitStore,
        backend,
        workspace_root: str,
        enable_mcp_filesystem: bool = False,
        enable_mcp_git: bool = False,
        enable_mcp_bash: bool = False,
        enable_mcp_process: bool = False,
    ):
        self.store = store
        self.backend = backend
        self.workspace_root = workspace_root
        self.tool_registry = ToolRegistry(Path(workspace_root))
        if enable_mcp_filesystem:
            bootstrap = bootstrap_local_filesystem_mcp_server(workspace_root=workspace_root)
            register_mcp_server_tools(registry=self.tool_registry, bootstrap=bootstrap)
        if enable_mcp_git:
            bootstrap = bootstrap_local_git_mcp_server(workspace_root=workspace_root)
            register_mcp_server_tools(registry=self.tool_registry, bootstrap=bootstrap)
        if enable_mcp_bash:
            bootstrap = bootstrap_local_bash_mcp_server(workspace_root=workspace_root)
            register_mcp_server_tools(registry=self.tool_registry, bootstrap=bootstrap)
        if enable_mcp_process:
            bootstrap = bootstrap_local_process_mcp_server(workspace_root=workspace_root)
            register_mcp_server_tools(registry=self.tool_registry, bootstrap=bootstrap)
        if hasattr(self.backend, "tool_registry"):
            self.backend.tool_registry = self.tool_registry
        self.memory_service = MemoryService(store=self.store)
        if hasattr(self.backend, "memory_service"):
            self.backend.memory_service = self.memory_service

    def create_session(self, *, backend_name: str, model: str, conversation_id: str | None = None) -> ConversationSession:
        session = ConversationSession(conversation_id=conversation_id or new_id(f"conversation_{backend_name}"), backend_name=backend_name, model=model)
        setattr(session, "_store", self.store)
        self.store.save_session(session)
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        session = self.store.get_session(session_id)
        if session is not None:
            setattr(session, "_store", self.store)
        return session

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

    def _capture_memory_after_turn(self, *, session: ConversationSession) -> None:
        """Persist a bounded first-slice memory summary after a completed turn."""
        messages = self.list_messages(session.session_id)
        assistant_message = next((message for message in reversed(messages) if message.role == MessageRole.ASSISTANT and message.content.strip()), None)
        user_message = None
        if assistant_message is not None:
            for message in reversed(messages):
                if message.created_at <= assistant_message.created_at and message.role == MessageRole.USER and message.content.strip():
                    user_message = message
                    break
        records = self.memory_service.capture_turn_memory(
            session_id=session.session_id,
            run_id=session.conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        if records:
            session.metadata["last_memory_capture"] = {
                "memory_ids": [record.memory_id for record in records],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "count": len(records),
            }
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)

    def append_context_artifact_for_session(self, *, session_id: str, artifact_type: str, content: str, source: str) -> ContextArtifact | None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        conversation_id = getattr(session, "conversation_id", None)
        if not conversation_id:
            return None
        artifact = ContextArtifact(
            run_id=conversation_id,
            artifact_type=artifact_type,
            content=content,
            source=source,
        )
        self.store.save_context_artifact(artifact)
        return artifact

    def append_run_descriptor_for_session(self, *, session_id: str, descriptor: RunDescriptor) -> ContextArtifact | None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        session.metadata["active_run_descriptor"] = descriptor.model_dump(mode="json")
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)
        return self.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="run_descriptor",
            content=descriptor.model_dump_json(indent=2),
            source="runtime_contract",
        )

    def emit_session_event(self, *, session_id: str, event_type: RuntimeEventType, payload: dict) -> ExecutionEvent | None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        conversation_id = getattr(session, "conversation_id", None)
        if not conversation_id:
            return None
        event = ExecutionEvent(run_id=conversation_id, event_type=event_type, payload=payload)
        self.store.save_event(event)
        return event

    def _consume_pending_turn_snapshots(self, session: ConversationSession) -> None:
        metadata = session.metadata if isinstance(session.metadata, dict) else {}
        context_snapshot = metadata.pop("_pending_context_assembly", None)
        payload_snapshot = metadata.pop("_pending_provider_payload", None)
        if context_snapshot is not None:
            metadata["last_context_assembly"] = context_snapshot
            self.append_context_artifact_for_session(
                session_id=session.session_id,
                artifact_type="session_context_assembly",
                content=json.dumps(context_snapshot, indent=2, ensure_ascii=False),
                source="context_assembly",
            )
        if payload_snapshot is not None:
            metadata["last_provider_payload"] = payload_snapshot
            self.append_context_artifact_for_session(
                session_id=session.session_id,
                artifact_type="session_provider_payload",
                content=json.dumps(payload_snapshot, indent=2, ensure_ascii=False),
                source="provider_payload",
            )
        if context_snapshot is not None or payload_snapshot is not None:
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)

    def execute_tool_request(self, *, session: ConversationSession | None = None, tool_request: ToolRequest) -> ToolResult:
        """Execute one normalized tool request against the local registry."""
        unchanged_result = self.maybe_make_filesystem_unchanged_result(session=session, tool_request=tool_request)
        if unchanged_result is not None:
            return unchanged_result
        write_gate_result = self.maybe_block_write_for_grounding(session=session, tool_request=tool_request)
        if write_gate_result is not None:
            return write_gate_result
        tool = self.tool_registry.get(tool_request.tool_name)
        return tool.invoke(**tool_request.input_payload)

    def maybe_block_write_for_grounding(self, *, session: ConversationSession | None, tool_request: ToolRequest) -> ToolResult | None:
        if session is None or tool_request.tool_name not in {"native__write_file", "native__replace_in_file", "native__replace_all_in_file", "native__replace_block_in_file", "native__apply_exact_hunk", "replace_in_file", "apply_unified_patch"}:
            return None
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return None
        return None

    def _mutation_kind_for_tool(self, tool_name: str) -> str | None:
        return {
            "native__write_file": "write_file",
            "native__replace_in_file": "replace_in_file",
            "native__replace_all_in_file": "replace_all_in_file",
            "native__replace_block_in_file": "replace_block_in_file",
            "native__apply_exact_hunk": "apply_exact_hunk",
            "replace_in_file": "replace_in_file",
            "apply_unified_patch": "apply_unified_patch",
        }.get(tool_name)

    def maybe_make_filesystem_unchanged_result(self, *, session: ConversationSession | None, tool_request: ToolRequest) -> ToolResult | None:
        if session is None or tool_request.tool_name != "read_file":
            return None
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return None
        read_state = session.metadata.get("filesystem_read_state", {})
        if not isinstance(read_state, dict):
            return None
        prior = read_state.get(path)
        if not isinstance(prior, dict):
            return None
        grounding_status = self.filesystem_grounding_status_for_path(session=session, path=path)
        if grounding_status.get("status") != "full_read_fresh":
            return None
        observed_modified_at = prior.get("observed_modified_at_epoch")
        observed_size_bytes = prior.get("observed_size_bytes")
        structured = {
            "path": path,
            "status": "unchanged",
            "grounding_kind": "full_read",
            "freshness_basis": {
                "modified_at_epoch": observed_modified_at,
                "size_bytes": observed_size_bytes,
            },
            "range": None,
        }
        return ToolResult(
            ok=True,
            content=f"File {path} unchanged since prior full read in this session.",
            data={
                "result_kind": "filesystem_unchanged",
                "raw_result": {"structuredContent": structured},
            },
        )

    def filesystem_grounding_kind_for_tool(self, tool_name: str, *, is_partial_view: bool) -> str | None:
        if tool_name == "read_file":
            return "partial_read" if is_partial_view else "full_read"
        return None

    def filesystem_grounding_status_for_path(self, *, session: ConversationSession, path: str) -> dict[str, Any]:
        read_state = session.metadata.get("filesystem_read_state", {})
        if not isinstance(read_state, dict):
            return {"status": "none", "path": path, "grounding_kind": None, "fresh": False}
        state = read_state.get(path)
        if not isinstance(state, dict):
            return {"status": "none", "path": path, "grounding_kind": None, "fresh": False}
        grounding_kind = state.get("grounding_kind")
        if grounding_kind == "partial_read":
            return {"status": "partial_only", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        if grounding_kind != "full_read":
            return {"status": "none", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        workspace_root = Path(self.workspace_root).resolve()
        target = (workspace_root / path).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        if not target.exists() or not target.is_file():
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        try:
            stat = target.stat()
        except OSError:
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        observed_modified_at = state.get("observed_modified_at_epoch")
        observed_size_bytes = state.get("observed_size_bytes")
        fresh = observed_modified_at is not None and observed_size_bytes is not None and stat.st_mtime == observed_modified_at and stat.st_size == observed_size_bytes
        return {
            "status": "full_read_fresh" if fresh else "full_read_stale",
            "path": path,
            "grounding_kind": grounding_kind,
            "fresh": fresh,
        }

    def filesystem_write_readiness_for_path(self, *, session: ConversationSession, path: str) -> dict[str, Any]:
        grounding = self.filesystem_grounding_status_for_path(session=session, path=path)
        status = grounding.get("status")
        if status == "full_read_fresh":
            return {
                "eligible": True,
                "path": path,
                "grounding_status": status,
                "reason": "full_read_fresh_grounding_available",
            }
        if status == "partial_only":
            reason = "partial_read_grounding_insufficient"
        elif status == "full_read_stale":
            reason = "stale_full_read_grounding"
        else:
            reason = "no_prior_grounding"
        return {
            "eligible": False,
            "path": path,
            "grounding_status": status,
            "reason": reason,
        }

    def record_filesystem_read_state(self, *, session: ConversationSession, tool_request: ToolRequest, tool_result: ToolResult) -> None:
        if not tool_result.ok:
            return
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return
        tool_data = tool_result.data if isinstance(tool_result.data, dict) else {}
        raw_result = tool_data.get("raw_result") if isinstance(tool_data, dict) else {}
        structured = raw_result.get("structuredContent") if isinstance(raw_result, dict) else {}
        if isinstance(structured, dict) and structured.get("status") == "unchanged":
            return
        truncated = bool(structured.get("truncated")) if isinstance(structured, dict) else False
        grounding_kind = self.filesystem_grounding_kind_for_tool(tool_request.tool_name, is_partial_view=truncated)
        if grounding_kind is None:
            return
        read_state = session.metadata.setdefault("filesystem_read_state", {})
        observed_modified_at = structured.get("modified_at_epoch") if isinstance(structured, dict) else None
        observed_size_bytes = structured.get("size_bytes") if isinstance(structured, dict) else None
        read_state[path] = {
            "source_tool": tool_request.tool_name,
            "timestamp_epoch": datetime.now(timezone.utc).timestamp(),
            "is_partial_view": truncated,
            "grounding_kind": grounding_kind,
            "path_kind": "file",
            "observed_modified_at_epoch": observed_modified_at,
            "observed_size_bytes": observed_size_bytes,
            "range": None,
        }
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

    def append_tool_result_message(self, *, session_id: str, tool_request: ToolRequest, tool_result: ToolResult) -> ConversationMessage:
        """Append a simple transcript-visible tool result message."""
        if tool_result.ok:
            content = f"Tool result from {tool_request.tool_name}:\n{tool_result.content}"
        else:
            content = f"Tool result from {tool_request.tool_name} (error):\n{tool_result.content}"
        self.emit_session_event(
            session_id=session_id,
            event_type=RuntimeEventType.TOOL_INVOCATION_COMPLETED,
            payload={"tool_name": tool_request.tool_name, "ok": tool_result.ok, "side_effect_class": tool_request.side_effect_class},
        )
        return self.append_message(
            session_id=session_id,
            role=MessageRole.TOOL,
            content=content,
            metadata={
                "message_kind": "tool_result",
                "tool_name": tool_request.tool_name,
                "tool_ok": tool_result.ok,
                "side_effect_class": tool_request.side_effect_class,
                "tool_data": tool_result.data or {},
            },
        )

    def run_session_turn(self, *, session_id: str, user_input: str, descriptor: RunDescriptor | None = None, on_assistant_partial_text=None) -> ExecutionPlan:
        """Execute one canonical session turn and return its bounded result.

        Current MVP closure contract:
        - plain-text turns append the assistant reply and return a final-text plan
        - non-approval tool turns execute their governed tool closure internally
          and return the post-tool continuation/final plan
        - approval-gated tool turns persist waiting state and return a waiting plan;
          resumption continues through ``resolve_session_approval(...)``
        """
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        if session.metadata.get("terminated"):
            raise ValueError(f"session terminated: {session_id}")
        pending = self._get_pending_approval(session)
        if pending is not None:
            raise ValueError(f"session has pending approval: {pending['approval_request_id']}")
        if descriptor is not None:
            self.append_run_descriptor_for_session(session_id=session_id, descriptor=descriptor)
            refreshed = self.get_session(session_id)
            if refreshed is None:
                raise ValueError(f"session not found after recording run descriptor: {session_id}")
            session = refreshed
        self.append_message(session_id=session_id, role=MessageRole.USER, content=user_input)
        self.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="session_user_input",
            content=user_input,
            source="user_input",
        )
        self.emit_session_event(
            session_id=session_id,
            event_type=RuntimeEventType.RUN_STARTED,
            payload={
                "session_id": session_id,
                "user_input": user_input,
                "mode": "session_turn",
                "has_run_descriptor": descriptor is not None,
            },
        )
        messages = self.list_messages(session_id)
        self.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="session_transcript_snapshot",
            content=json.dumps([
                {
                    "role": getattr(message.role, "value", str(message.role)),
                    "content": message.content,
                    "turn_index": message.turn_index,
                    "metadata": message.metadata,
                }
                for message in messages
            ], indent=2, ensure_ascii=False),
            source="runtime",
        )
        try:
            plan = self._plan_from_messages(session=session, messages=messages, on_assistant_partial_text=on_assistant_partial_text)
            self._consume_pending_turn_snapshots(session)
            refreshed_after_plan = self.get_session(session_id)
            if refreshed_after_plan is not None:
                session = refreshed_after_plan
        except OpenAIAuthStoreError as exc:
            failure_message = str(exc)
            self.emit_session_event(
                session_id=session_id,
                event_type=RuntimeEventType.RUN_FAILED,
                payload={
                    "kind": "auth_failure",
                    "source_backend": getattr(self.backend, "backend_name", session.backend_name),
                    "failure_reason": failure_message,
                },
            )
            self.append_context_artifact_for_session(
                session_id=session_id,
                artifact_type="session_auth_failure",
                content=f"backend={getattr(self.backend, 'backend_name', session.backend_name)}\nmessage={failure_message}",
                source="auth",
            )
            session.metadata["last_auth_failure"] = {
                "backend": getattr(self.backend, "backend_name", session.backend_name),
                "message": failure_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)
            return ExecutionPlan(
                source_backend=getattr(self.backend, "backend_name", session.backend_name),
                plan_label="auth-failure",
                failure_reason=failure_message,
            )

        return self._finalize_session_plan(session=session, plan=plan, messages=messages)

    def list_open_session_approvals(self) -> list[dict]:
        """Return session-scoped pending approvals for the current lightweight path."""
        approvals: list[dict] = []
        for session in self.store.list_sessions():
            pending = self._get_pending_approval(session)
            if pending is not None:
                approvals.append(
                    {
                        "session_id": session.session_id,
                        "conversation_id": session.conversation_id,
                        **pending,
                    }
                )
        return approvals

    def resolve_session_approval(self, *, session_id: str, approval_request_id: str, decision: str, note: str | None = None) -> ExecutionPlan:
        """Resolve one waiting approval and return the resumed bounded turn result.

        Current MVP resumed-turn contract:
        - ``approve`` continues through governed tool execution and then returns
          the post-tool bounded result
        - ``reject`` continues truthfully without tool execution and returns the
          bounded post-rejection continuation result
        """
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        pending = self._get_pending_approval(session)
        if pending is None:
            raise ValueError(f"session has no pending approval: {session_id}")
        if pending["approval_request_id"] != approval_request_id:
            raise ValueError(f"approval request does not match pending session approval: {approval_request_id}")

        tool_request = ToolRequest.model_validate(pending["tool_request"])
        if decision not in {"approve", "reject"}:
            raise ValueError(f"unsupported approval decision: {decision}")
        self._clear_pending_approval(session)

        if decision == "approve":
            self.emit_session_event(
                session_id=session_id,
                event_type=RuntimeEventType.APPROVAL_GRANTED,
                payload={"approval_request_id": approval_request_id, "tool_name": tool_request.tool_name},
            )
            self.append_message(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=f"Approval granted for {tool_request.tool_name}. Continuing with governed tool execution.",
                metadata={
                    "message_kind": "approval_decision",
                    "approval_request_id": approval_request_id,
                    "decision": "approved",
                    "note": note,
                    "tool_name": tool_request.tool_name,
                },
            )
            refreshed = self.get_session(session_id)
            if refreshed is not None:
                session = refreshed
            self._transition_governed_tool_state(session, "approved", note=note)
            refreshed = self.get_session(session_id)
            if refreshed is not None:
                session = refreshed
            return self._execute_non_approval_tool_closure(session=session, initial_plan=ExecutionPlan(source_backend=pending['source_backend'], plan_label=f"{pending['plan_label']}-approved", tool_request=tool_request, should_finish_after_tool=False))

        if decision == "reject":
            rejection_text = f"Approval rejected for {tool_request.tool_name}. The requested tool was not executed."
            if note:
                rejection_text += f" Note: {note}"
            self.emit_session_event(
                session_id=session_id,
                event_type=RuntimeEventType.APPROVAL_REJECTED,
                payload={"approval_request_id": approval_request_id, "tool_name": tool_request.tool_name},
            )
            self.append_message(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=rejection_text,
                metadata={
                    "message_kind": "approval_decision",
                    "approval_request_id": approval_request_id,
                    "decision": "rejected",
                    "note": note,
                    "tool_name": tool_request.tool_name,
                    "tool_executed": False,
                },
            )
            self._transition_governed_tool_state(session, "rejected", note=note)
            self._mark_permission_authority_rejection(session=session, tool_name=tool_request.tool_name)
            updated_messages = self.list_messages(session_id)
            continuation_context = build_rejection_continuation_context(updated_messages)
            continuation_messages = list(updated_messages)
            if continuation_context is not None and continuation_context.bridge_message is not None:
                continuation_messages.append(continuation_context.bridge_message)
            continuation_plan = self._plan_from_messages(session=session, messages=continuation_messages)
            return self._finalize_session_plan(
                session=session,
                plan=continuation_plan,
                messages=updated_messages,
                continued_after_tool_rejection=True,
                rejected_tool_name=tool_request.tool_name,
                used_continuation_bridge=continuation_context is not None and continuation_context.bridge_message is not None,
            )

        raise ValueError(f"unsupported approval decision: {decision}")

    def _execute_non_approval_tool_closure(self, *, session: ConversationSession, initial_plan: ExecutionPlan) -> ExecutionPlan:
        """Execute one non-approval tool request as an in-turn closure step.

        This helper is part of the canonical ``run_session_turn(...)`` path,
        not an external second-stage continuation contract. It executes one
        allowed tool request, appends the transcript-visible tool result, then
        replans once and returns the bounded post-tool result for the same turn.
        """
        if initial_plan.tool_request is None:
            raise ValueError("initial_plan must include a tool request")
        tool_request = initial_plan.tool_request
        invocation = ToolInvocation(
            run_id=session.conversation_id,
            step_id=f"session_turn:{session.session_id}",
            tool_name=tool_request.tool_name,
            input_payload=tool_request.input_payload,
            status=ToolInvocationStatus.EXECUTING,
            started_at=datetime.now(timezone.utc),
            side_effect_class=tool_request.side_effect_class,
        )
        self.store.save_tool_invocation(invocation)
        tool_result = self.execute_tool_request(session=session, tool_request=tool_request)
        self.record_filesystem_read_state(session=session, tool_request=tool_request, tool_result=tool_result)
        if session.governed_tool_state is not None and session.governed_tool_state.tool_name == initial_plan.tool_request.tool_name:
            self._transition_governed_tool_state(
                session,
                "executed",
                note="tool executed successfully" if tool_result.ok else "tool execution returned a non-ok result",
            )
        else:
            self._set_governed_tool_state(
                session,
                GovernedToolState(
                    tool_name=initial_plan.tool_request.tool_name,
                    state="executed",
                    side_effect_class=initial_plan.tool_request.side_effect_class,
                    input_payload=initial_plan.tool_request.input_payload,
                    note="tool executed successfully" if tool_result.ok else "tool execution returned a non-ok result",
                ),
            )
        invocation.status = ToolInvocationStatus.COMPLETED if tool_result.ok else ToolInvocationStatus.FAILED
        invocation.ended_at = datetime.now(timezone.utc)
        invocation.result_payload = tool_result.model_dump(mode="json")
        self.store.save_tool_invocation(invocation)
        self.append_tool_result_message(session_id=session.session_id, tool_request=initial_plan.tool_request, tool_result=tool_result)
        refreshed = self.get_session(session.session_id)
        if refreshed is not None:
            session = refreshed
        updated_messages = self.list_messages(session.session_id)
        final_plan = self._plan_from_messages(session=session, messages=updated_messages)
        finalized_plan = self._finalize_session_plan(session=session, plan=final_plan, messages=updated_messages)
        return finalized_plan

    def _finalize_session_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        continued_after_tool_rejection: bool = False,
        rejected_tool_name: str | None = None,
        used_continuation_bridge: bool = False,
    ) -> ExecutionPlan:
        """Apply lightweight runtime guardrails before returning a session plan.

        Current guardrail:
        - if a tool was already rejected in this session and the provider tries to
          immediately reissue the same tool, do not reopen the same approval loop
          in the same continuation path
        """
        if plan.tool_request is not None and rejected_tool_name is not None:
            governance = self._get_tool_governance_metadata(plan.tool_request.tool_name)
            policy_group = governance["policy_group"]
            if plan.tool_request.tool_name == rejected_tool_name:
                guard_text = (
                    f"The tool {rejected_tool_name} was already rejected in this continuation path and will not be requested again automatically. "
                    "Continue without reissuing that tool unless the human explicitly asks again in a later turn."
                )
                guarded_plan = ExecutionPlan(
                    source_backend=plan.source_backend,
                    plan_label=f"{plan.plan_label}-guarded-rejected-tool-reissue",
                    final_text=guard_text,
                    should_finish_after_tool=True,
                )
                if session.governed_tool_state is not None and session.governed_tool_state.tool_name == rejected_tool_name:
                    self._transition_governed_tool_state(session, "blocked_reissue", note="runtime guardrail blocked rejected tool reissue")
                else:
                    self._set_governed_tool_state(
                        session,
                        GovernedToolState(
                            tool_name=rejected_tool_name,
                            state="blocked_reissue",
                            side_effect_class=plan.tool_request.side_effect_class if plan.tool_request else "safe",
                            input_payload=plan.tool_request.input_payload if plan.tool_request else {},
                            note="runtime guardrail blocked rejected tool reissue",
                        ),
                    )
                self.append_context_artifact_for_session(
                    session_id=session.session_id,
                    artifact_type="session_guardrail_block",
                    content=f"guardrail_kind=rejected_tool_reissue\ntool_name={rejected_tool_name}\nplan_label={plan.plan_label}",
                    source="governance",
                )
                self.emit_session_event(
                    session_id=session.session_id,
                    event_type=RuntimeEventType.RUN_FAILED,
                    payload={"kind": "guardrail_block", "guardrail_kind": "rejected_tool_reissue", "tool_name": rejected_tool_name},
                )
                self.append_message(
                    session_id=session.session_id,
                    role=MessageRole.ASSISTANT,
                    content=guard_text,
                    metadata={
                        "message_kind": "guardrail_block",
                        "guardrail_kind": "rejected_tool_reissue",
                        "tool_name": rejected_tool_name,
                        "source_backend": plan.source_backend,
                        "continued_after_tool_rejection": continued_after_tool_rejection,
                        "used_continuation_bridge": used_continuation_bridge,
                    },
                )
                return guarded_plan

        if plan.failure_reason:
            self.emit_session_event(
                session_id=session.session_id,
                event_type=RuntimeEventType.RUN_FAILED,
                payload={
                    "kind": "runtime_failure",
                    "source_backend": plan.source_backend,
                    "plan_label": plan.plan_label,
                    "failure_reason": plan.failure_reason,
                },
            )
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=plan.failure_reason,
                metadata={
                    "message_kind": "runtime_failure",
                    "source_backend": plan.source_backend,
                    "plan_label": plan.plan_label,
                    "failure_reason": plan.failure_reason,
                    "continued_after_tool_rejection": continued_after_tool_rejection,
                    "tool_name": rejected_tool_name,
                    "used_continuation_bridge": used_continuation_bridge,
                },
            )
            return plan
        if plan.tool_request is None and continued_after_tool_rejection and plan.final_text:
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=plan.final_text,
                metadata={
                    "source_backend": plan.source_backend,
                    "plan_label": plan.plan_label,
                    "continued_after_tool_rejection": True,
                    "tool_name": rejected_tool_name,
                    "used_continuation_bridge": used_continuation_bridge,
                },
            )
            refreshed = self.get_session(session.session_id)
            if refreshed is not None:
                self._capture_memory_after_turn(session=refreshed)
        elif plan.tool_request is None and plan.final_text:
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=plan.final_text,
                metadata={"source_backend": plan.source_backend, "plan_label": plan.plan_label},
            )
            refreshed = self.get_session(session.session_id)
            if refreshed is not None:
                self._capture_memory_after_turn(session=refreshed)
        elif plan.tool_request is not None:
            decision = self._evaluate_policy_for_plan(
                session=session,
                plan=plan,
                rejected_tool_name=rejected_tool_name,
            )
            return self._apply_policy_decision(session=session, plan=plan, decision=decision)
        return plan

    def _evaluate_policy_for_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        rejected_tool_name: str | None,
    ) -> PolicyDecision:
        if plan.tool_request is None:
            raise ValueError("policy evaluation requires a tool request")

        tool_request = plan.tool_request
        governance = self._get_tool_governance_metadata(tool_request.tool_name)
        policy_group = governance["policy_group"]
        appearance_count_after_rejection = self._increment_appearance_count_after_rejection(
            session=session,
            tool_name=tool_request.tool_name,
        )
        environment_status = self._resolve_environment_status_for_tool_request(tool_request)
        ctx = PolicyEvaluationInput(
            policy_group=policy_group,
            approval_required=tool_request.requires_approval,
            appearance_count_after_rejection=appearance_count_after_rejection,
            has_structured_reauthorization=self._has_structured_reauthorization(session=session, tool_name=tool_request.tool_name),
            environment_status=environment_status,
            tool_name=tool_request.tool_name,
        )
        return evaluate_tool_approval_policy(ctx)

    def _apply_policy_decision(self, *, session: ConversationSession, plan: ExecutionPlan, decision: PolicyDecision) -> ExecutionPlan:
        if plan.tool_request is None:
            raise ValueError("policy application requires a tool request")

        tool_request = plan.tool_request
        if decision.outcome == "allow":
            return self._execute_non_approval_tool_closure(session=session, initial_plan=plan)
        if decision.outcome == "require_approval":
            return self._open_session_approval(session=session, tool_request=tool_request, plan=plan)

        if decision.outcome == "loud_caution":
            self.append_context_artifact_for_session(
                session_id=session.session_id,
                artifact_type="session_policy_caution",
                content=f"tool_name={tool_request.tool_name}\npolicy_group={decision.policy_group}\nreason={decision.reason}",
                source="governance",
            )
            self.emit_session_event(
                session_id=session.session_id,
                event_type=RuntimeEventType.RUN_FAILED,
                payload={"kind": "policy_caution", "tool_name": tool_request.tool_name, "policy_group": decision.policy_group, "reason": decision.reason},
            )
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=decision.explanation,
                metadata={
                    "message_kind": "policy_caution",
                    "policy_group": decision.policy_group,
                    "tool_name": tool_request.tool_name,
                    "reason": decision.reason,
                },
            )
            return ExecutionPlan(source_backend=plan.source_backend, plan_label=f"{plan.plan_label}-policy-caution", final_text=decision.explanation, should_finish_after_tool=True)

        if decision.outcome == "terminate_session":
            session.metadata["terminated"] = True
            session.metadata["termination_reason"] = decision.reason
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)
            self.append_context_artifact_for_session(
                session_id=session.session_id,
                artifact_type="session_policy_termination",
                content=f"tool_name={tool_request.tool_name}\npolicy_group={decision.policy_group}\nreason={decision.reason}",
                source="governance",
            )
            self.emit_session_event(
                session_id=session.session_id,
                event_type=RuntimeEventType.RUN_FAILED,
                payload={"kind": "policy_termination", "tool_name": tool_request.tool_name, "policy_group": decision.policy_group, "reason": decision.reason},
            )
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=decision.explanation,
                metadata={
                    "message_kind": "policy_termination",
                    "policy_group": decision.policy_group,
                    "tool_name": tool_request.tool_name,
                    "reason": decision.reason,
                },
            )
            return ExecutionPlan(source_backend=plan.source_backend, plan_label=f"{plan.plan_label}-terminated", final_text=decision.explanation, should_finish_after_tool=True)

        if decision.outcome in {"deny", "recheck_environment"}:
            invocation = ToolInvocation(
                run_id=session.conversation_id,
                step_id=f"session_turn:{session.session_id}",
                tool_name=tool_request.tool_name,
                input_payload=tool_request.input_payload,
                status=ToolInvocationStatus.FAILED,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
                side_effect_class=tool_request.side_effect_class,
                result_payload={
                    "ok": False,
                    "content": decision.explanation,
                    "data": {
                        "failure_kind": "policy_decision",
                        "policy_group": decision.policy_group,
                        "reason": decision.reason,
                        "outcome": decision.outcome,
                    },
                },
            )
            self.store.save_tool_invocation(invocation)
            self.append_context_artifact_for_session(
                session_id=session.session_id,
                artifact_type="session_policy_decision",
                content=f"tool_name={tool_request.tool_name}\npolicy_group={decision.policy_group}\nreason={decision.reason}\noutcome={decision.outcome}",
                source="governance",
            )
            self.emit_session_event(
                session_id=session.session_id,
                event_type=RuntimeEventType.RUN_FAILED,
                payload={"kind": "policy_decision", "tool_name": tool_request.tool_name, "policy_group": decision.policy_group, "reason": decision.reason, "outcome": decision.outcome},
            )
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=decision.explanation,
                metadata={
                    "message_kind": "policy_decision",
                    "policy_group": decision.policy_group,
                    "tool_name": tool_request.tool_name,
                    "reason": decision.reason,
                    "outcome": decision.outcome,
                },
            )
            return ExecutionPlan(source_backend=plan.source_backend, plan_label=f"{plan.plan_label}-{decision.outcome}", final_text=decision.explanation, should_finish_after_tool=True)

        raise ValueError(f"unsupported policy outcome: {decision.outcome}")

    def _get_tool_governance_metadata(self, tool_name: str) -> dict[str, str]:
        tool = self.tool_registry.get(tool_name)
        if hasattr(tool, "governance_metadata"):
            return tool.governance_metadata()
        return {
            "policy_group": getattr(tool, "governance_policy_group", "system_environment"),
            "environment_check_kind": getattr(tool, "environment_check_kind", "none"),
        }

    def _resolve_environment_status_for_tool_request(self, tool_request: ToolRequest) -> str:
        governance = self._get_tool_governance_metadata(tool_request.tool_name)
        check_kind = governance.get("environment_check_kind", "none")
        if check_kind == "none":
            return "ok"
        if check_kind == "path_exists":
            path = tool_request.input_payload.get("path")
            if not path:
                tool = self.tool_registry.get(tool_request.tool_name)
                if getattr(tool, "tool_source", None) == "mcp" and getattr(tool, "original_name", None) in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                    path = "."
                    tool_request.input_payload["path"] = path
                else:
                    return "unknown"

            tool = self.tool_registry.get(tool_request.tool_name)
            if getattr(tool, "tool_source", None) == "mcp" and getattr(tool, "original_name", None) in {"read_file", "list_directory", "list_directory_with_sizes", "directory_tree", "search_files", "get_file_info"}:
                client = getattr(tool, "client", None)
                bootstrap = getattr(client, "bootstrap", None) if client is not None else None
                server_args = getattr(bootstrap, "args", []) if bootstrap is not None else []
                server_env = getattr(bootstrap, "env", {}) if bootstrap is not None else {}
                target = resolve_filesystem_mcp_target_path(
                    input_payload=tool_request.input_payload,
                    server_args=server_args,
                    server_env=server_env,
                )
                allowed_root = Path(server_env["ORBIT_WORKSPACE_ROOT"]).resolve() if server_env.get("ORBIT_WORKSPACE_ROOT") else None
                if allowed_root is None and server_args:
                    allowed_root = Path(server_args[-1]).resolve()
                if target is None or allowed_root is None:
                    return "unknown"
                try:
                    target.relative_to(allowed_root)
                except ValueError:
                    return "denied"
                original_name = getattr(tool, "original_name", None)
                if original_name in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                    return "ok" if target.exists() and target.is_dir() else "denied"
                return "ok" if target.exists() and target.is_file() else "denied"

            workspace_root = Path(self.workspace_root).resolve()
            target = (workspace_root / path).resolve()
            if not str(target).startswith(str(workspace_root)):
                return "denied"
            return "ok" if target.exists() and target.is_file() else "denied"
        return "unknown"

    def _mark_permission_authority_rejection(self, *, session: ConversationSession, tool_name: str) -> None:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        permission_tracking[tool_name] = {
            "rejection_active": True,
            "appearance_count_after_rejection": 0,
        }
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

    def _get_appearance_count_after_rejection(self, *, session: ConversationSession, tool_name: str) -> int:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        return int(tool_tracking.get("appearance_count_after_rejection", 0))

    def _increment_appearance_count_after_rejection(self, *, session: ConversationSession, tool_name: str) -> int:
        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        if tool_tracking.get("rejection_active"):
            tool_tracking["appearance_count_after_rejection"] = int(tool_tracking.get("appearance_count_after_rejection", 0)) + 1
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)
        return int(tool_tracking.get("appearance_count_after_rejection", 0))

    def reauthorize_tool_path(
        self,
        *,
        session_id: str,
        tool_name: str,
        note: str | None = None,
        source: str = "runtime_entry",
    ) -> dict:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        if session.metadata.get("terminated"):
            raise ValueError(f"cannot reauthorize terminated session: {session_id}")

        tracking = session.metadata.setdefault("policy_tracking", {})
        permission_tracking = tracking.setdefault("permission_authority", {})
        tool_tracking = permission_tracking.setdefault(
            tool_name,
            {
                "rejection_active": False,
                "appearance_count_after_rejection": 0,
            },
        )
        tool_tracking["rejection_active"] = False
        tool_tracking["appearance_count_after_rejection"] = 0

        structured = session.metadata.setdefault("structured_reauthorization", {})
        record = {
            "active": True,
            "source": source,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        structured[tool_name] = record
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

        message_text = f"Structured reauthorization recorded for {tool_name}. Future requests for this tool may re-enter the governed approval path."
        if note:
            message_text += f" Note: {note}"
        self.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type="session_structured_reauthorization",
            content=f"tool_name={tool_name}\nsource={source}\nnote={note or ''}",
            source="governance",
        )
        self.emit_session_event(
            session_id=session_id,
            event_type=RuntimeEventType.APPROVAL_GRANTED,
            payload={"kind": "structured_reauthorization", "tool_name": tool_name, "source": source},
        )
        self.append_message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=message_text,
            metadata={
                "message_kind": "structured_reauthorization",
                "tool_name": tool_name,
                "source": source,
                "note": note,
            },
        )
        return {
            "session_id": session_id,
            "tool_name": tool_name,
            "source": source,
            "note": note,
            **record,
        }

    def _has_structured_reauthorization(self, *, session: ConversationSession, tool_name: str) -> bool:
        structured = session.metadata.get("structured_reauthorization")
        if not isinstance(structured, dict):
            return False
        tool_record = structured.get(tool_name)
        return isinstance(tool_record, dict) and bool(tool_record.get("active"))

    def _get_pending_approval(self, session: ConversationSession) -> dict | None:
        pending = session.metadata.get("pending_approval")
        return pending if isinstance(pending, dict) else None

    def _set_governed_tool_state(self, session: ConversationSession, state: GovernedToolState | None) -> None:
        session.governed_tool_state = state
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

    def _transition_governed_tool_state(self, session: ConversationSession, new_state: str, *, note: str | None = None) -> None:
        """Advance the current governed-tool state through validated transitions."""
        current = session.governed_tool_state
        if current is None:
            raise ValueError(f"session has no governed tool state to transition: {session.session_id}")
        self._set_governed_tool_state(session, current.transition(new_state, note=note))

    def _set_pending_approval(self, session: ConversationSession, pending: dict) -> None:
        session.metadata["pending_approval"] = pending
        governed_state = GovernedToolState(
            tool_name=pending["tool_request"].get("tool_name", "unknown"),
            state="waiting_for_approval",
            approval_request_id=pending.get("approval_request_id"),
            side_effect_class=pending["tool_request"].get("side_effect_class", "safe"),
            input_payload=pending["tool_request"].get("input_payload", {}),
        )
        self._set_governed_tool_state(session, governed_state)

    def _clear_pending_approval(self, session: ConversationSession) -> None:
        session.metadata.pop("pending_approval", None)
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

    def _open_session_approval(self, *, session: ConversationSession, tool_request: ToolRequest, plan: ExecutionPlan) -> ExecutionPlan:
        """Persist the canonical waiting boundary for an approval-gated turn.

        This method records the session-local pending approval truth, emits the
        coarse approval-requested runtime event, appends the transcript-visible
        approval request, and returns the waiting plan that must later resume
        through ``resolve_session_approval(...)``.
        """
        approval_request_id = new_id("approval")
        pending = {
            "approval_request_id": approval_request_id,
            "tool_request": tool_request.model_dump(mode="json"),
            "source_backend": plan.source_backend,
            "plan_label": plan.plan_label,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self._set_pending_approval(session, pending)
        self.emit_session_event(
            session_id=session.session_id,
            event_type=RuntimeEventType.APPROVAL_REQUESTED,
            payload={
                "approval_request_id": approval_request_id,
                "tool_name": tool_request.tool_name,
                "side_effect_class": tool_request.side_effect_class,
                "source_backend": plan.source_backend,
                "plan_label": plan.plan_label,
            },
        )
        approval_text = (
            f"Approval required before executing {tool_request.tool_name} "
            f"(side_effect_class={tool_request.side_effect_class})."
        )
        self.append_message(
            session_id=session.session_id,
            role=MessageRole.ASSISTANT,
            content=approval_text,
            metadata={
                "message_kind": "approval_request",
                "approval_request_id": approval_request_id,
                "tool_name": tool_request.tool_name,
                "side_effect_class": tool_request.side_effect_class,
                "source_backend": plan.source_backend,
                "plan_label": plan.plan_label,
            },
        )
        return ExecutionPlan(
            source_backend=plan.source_backend,
            plan_label=f"{plan.plan_label}-waiting-for-approval",
            tool_request=tool_request,
            should_finish_after_tool=False,
            failure_reason=None,
        )

    def _plan_from_messages(self, *, session: ConversationSession, messages: list[ConversationMessage], on_assistant_partial_text=None) -> ExecutionPlan:
        """Use history-aware provider path when available, otherwise fallback."""
        if hasattr(self.backend, "plan_from_messages"):
            return self.backend.plan_from_messages(messages, session=session, on_partial_text=on_assistant_partial_text)
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
