"""Session manager for ORBIT's first multi-turn non-tool/tool conversation paths."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from orbit.models import ContextArtifact, ConversationMessage, ConversationSession, ExecutionEvent, GovernedToolState, MessageRole, ToolInvocation, ToolInvocationStatus
from orbit.models.core import new_id
from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.governance.protocol.mode import ModePolicyDescriptor, RuntimeMode, build_mode_policy_snapshot
from orbit.runtime.core.events import RuntimeEventType
from orbit.runtime.execution.continuation_context import build_rejection_continuation_context
from orbit.runtime.governance.tool_approval_policy import PolicyDecision, PolicyEvaluationInput, evaluate_tool_approval_policy
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.store.base import OrbitStore
from orbit.tools.base import ToolResult
from orbit.tools.registry import ToolRegistry

SESSION_MANAGER_IMPORT_PROFILE_TIMINGS: dict[str, float] = {}


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
        runtime_mode: RuntimeMode = "dev",
        tool_registry: ToolRegistry | None = None,
        embedding_service=None,
        memory_service=None,
    ):
        t0 = time.perf_counter()
        self.store = store
        self.backend = backend
        self.workspace_root = workspace_root
        self.runtime_mode = runtime_mode
        self.metadata = {**getattr(self, 'metadata', {}), 'session_manager_profile_timings': {}}
        timings: dict[str, float] = self.metadata['session_manager_profile_timings']

        t_registry = time.perf_counter()
        self.tool_registry = tool_registry or ToolRegistry(Path(workspace_root))
        timings['tool_registry_init_ms'] = round((time.perf_counter() - t_registry) * 1000, 2)

        if hasattr(self.backend, "tool_registry"):
            t = time.perf_counter()
            self.backend.tool_registry = self.tool_registry
            timings['backend_tool_registry_bind_ms'] = round((time.perf_counter() - t) * 1000, 2)
        self.embedding_service = embedding_service
        self.memory_service = memory_service
        if self.memory_service is None:
            timings['memory_enabled'] = False
        timings['total_ms'] = round((time.perf_counter() - t0) * 1000, 2)
        self.metadata = {**getattr(self, 'metadata', {}), 'session_manager_profile_timings': timings}

    def create_session(self, *, backend_name: str, model: str, conversation_id: str | None = None, runtime_mode: RuntimeMode | None = None) -> ConversationSession:
        effective_runtime_mode = runtime_mode or self.runtime_mode
        session = ConversationSession(
            conversation_id=conversation_id or new_id(f"conversation_{backend_name}"),
            backend_name=backend_name,
            model=model,
            runtime_mode=effective_runtime_mode,
            metadata={"mode_policy": build_mode_policy_snapshot(runtime_mode=effective_runtime_mode, workspace_root=self.workspace_root)},
        )
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
        if self.memory_service is None:
            return
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
        from orbit.runtime.governance.grounding_service import GroundingGovernanceService

        grounding = GroundingGovernanceService(self)
        unchanged_result = grounding.maybe_make_unchanged_result(session=session, tool_request=tool_request)
        if unchanged_result is not None:
            return unchanged_result
        write_gate_result = grounding.maybe_block_mutation(session=session, tool_request=tool_request)
        if write_gate_result is not None:
            return write_gate_result
        tool = self.tool_registry.get(tool_request.tool_name)
        input_payload = dict(tool_request.input_payload)
        if (
            session is not None
            and getattr(tool, "tool_source", None) == "mcp"
            and getattr(tool, "server_name", None) == "process"
            and getattr(tool, "original_name", None) == "start_process"
        ):
            # Unconditionally overwrite session_id with the runtime session value.
            # This is the authoritative link between a spawned process and the owning session:
            # it enables session-scoped process listing and prevents cross-session handle leaks.
            # The model must not supply session_id; any caller-supplied value is discarded here.
            # Intentionally NOT guarded on 'not input_payload.get("session_id")': a permissive
            # guard would allow a model-supplied or planner-injected session_id to bypass this,
            # anchoring a process under a foreign session (prompt-injection vector).
            input_payload["session_id"] = session.session_id
        return tool.invoke(**input_payload)

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

    def run_session_turn(self, *, session_id: str, user_input: str, descriptor: RunDescriptor | None = None, on_assistant_partial_text=None, on_stream_completed=None) -> ExecutionPlan:
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
            plan = self._plan_from_messages(session=session, messages=messages, on_assistant_partial_text=on_assistant_partial_text, on_stream_completed=on_stream_completed)
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
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        ToolGovernanceService(self).clear_pending_approval(session)

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
            ToolGovernanceService(self).transition_governed_state(session, "approved", note=note)
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
            ToolGovernanceService(self).transition_governed_state(session, "rejected", note=note)
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
        from orbit.runtime.governance.grounding_service import GroundingGovernanceService

        GroundingGovernanceService(self).record_read_state(
            session=session,
            tool_request=tool_request,
            tool_result=tool_result,
        )
        if session.governed_tool_state is not None and session.governed_tool_state.tool_name == initial_plan.tool_request.tool_name:
            ToolGovernanceService(self).transition_governed_state(
                session,
                "executed",
                note="tool executed successfully" if tool_result.ok else "tool execution returned a non-ok result",
            )
        else:
            ToolGovernanceService(self).set_governed_tool_state(
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

    def _maybe_materialize_rejected_tool_reissue_guard(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        rejected_tool_name: str | None,
        continued_after_tool_rejection: bool,
        used_continuation_bridge: bool,
    ) -> ExecutionPlan | None:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        if plan.tool_request is None or rejected_tool_name is None:
            return None
        if plan.tool_request.tool_name != rejected_tool_name:
            return None

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
            ToolGovernanceService(self).transition_governed_state(session, "blocked_reissue", note="runtime guardrail blocked rejected tool reissue")
        else:
            ToolGovernanceService(self).set_governed_tool_state(
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

    def _materialize_non_tool_terminal_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        continued_after_tool_rejection: bool,
        rejected_tool_name: str | None,
        used_continuation_bridge: bool,
    ) -> ExecutionPlan | None:
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
            return plan
        if plan.tool_request is None and plan.final_text:
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=plan.final_text,
                metadata={"source_backend": plan.source_backend, "plan_label": plan.plan_label},
            )
            refreshed = self.get_session(session.session_id)
            if refreshed is not None:
                self._capture_memory_after_turn(session=refreshed)
            return plan
        return None

    def _route_tool_request_through_policy(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        rejected_tool_name: str | None,
    ) -> ExecutionPlan | None:
        if plan.tool_request is None:
            return None
        decision = self._evaluate_policy_for_plan(
            session=session,
            plan=plan,
            rejected_tool_name=rejected_tool_name,
        )
        return self._apply_policy_decision(session=session, plan=plan, decision=decision)

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
        """Apply lightweight runtime guardrails before returning a session plan."""
        guarded_plan = self._maybe_materialize_rejected_tool_reissue_guard(
            session=session,
            plan=plan,
            rejected_tool_name=rejected_tool_name,
            continued_after_tool_rejection=continued_after_tool_rejection,
            used_continuation_bridge=used_continuation_bridge,
        )
        if guarded_plan is not None:
            return guarded_plan

        terminal_plan = self._materialize_non_tool_terminal_plan(
            session=session,
            plan=plan,
            continued_after_tool_rejection=continued_after_tool_rejection,
            rejected_tool_name=rejected_tool_name,
            used_continuation_bridge=used_continuation_bridge,
        )
        if terminal_plan is not None:
            return terminal_plan

        routed_plan = self._route_tool_request_through_policy(
            session=session,
            plan=plan,
            rejected_tool_name=rejected_tool_name,
        )
        if routed_plan is not None:
            return routed_plan
        return plan

    def _evaluate_policy_for_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        rejected_tool_name: str | None,
    ) -> PolicyDecision:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        return ToolGovernanceService(self).evaluate_policy_for_plan(
            session=session,
            plan=plan,
            rejected_tool_name=rejected_tool_name,
        )

    def _apply_policy_decision(self, *, session: ConversationSession, plan: ExecutionPlan, decision: PolicyDecision) -> ExecutionPlan:
        if plan.tool_request is None:
            raise ValueError("policy application requires a tool request")

        tool_request = plan.tool_request
        if decision.outcome in {"allow", "require_approval"}:
            return self._apply_policy_execution_boundary(session=session, plan=plan, tool_request=tool_request, decision=decision)
        if decision.outcome in {"loud_caution", "terminate_session"}:
            return self._materialize_policy_message_outcome(session=session, plan=plan, tool_request=tool_request, decision=decision)
        if decision.outcome in {"deny", "recheck_environment"}:
            return self._materialize_governed_tool_failure_outcome(session=session, plan=plan, tool_request=tool_request, decision=decision)

        raise ValueError(f"unsupported policy outcome: {decision.outcome}")

    def _apply_policy_execution_boundary(self, *, session: ConversationSession, plan: ExecutionPlan, tool_request: ToolRequest, decision: PolicyDecision) -> ExecutionPlan:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        if decision.outcome == "allow":
            return self._execute_non_approval_tool_closure(session=session, initial_plan=plan)
        return ToolGovernanceService(self).open_session_approval(session=session, tool_request=tool_request, plan=plan)

    def _materialize_policy_outcome_from_spec(self, *, session: ConversationSession, plan: ExecutionPlan, decision: PolicyDecision, spec: dict) -> ExecutionPlan:
        self.append_context_artifact_for_session(
            session_id=session.session_id,
            artifact_type=spec["artifact_type"],
            content=spec["artifact_content"],
            source="governance",
        )
        self.emit_session_event(
            session_id=session.session_id,
            event_type=RuntimeEventType.RUN_FAILED,
            payload=spec["event_payload"],
        )
        self.append_message(
            session_id=session.session_id,
            role=MessageRole.ASSISTANT,
            content=spec["message_content"],
            metadata=spec["message_metadata"],
        )
        return ExecutionPlan(
            source_backend=plan.source_backend,
            plan_label=f"{plan.plan_label}-{spec['plan_suffix']}",
            final_text=decision.explanation,
            should_finish_after_tool=True,
        )

    def _materialize_policy_message_outcome(self, *, session: ConversationSession, plan: ExecutionPlan, tool_request: ToolRequest, decision: PolicyDecision) -> ExecutionPlan:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        spec = ToolGovernanceService(self).build_policy_message_outcome_spec(
            tool_request=tool_request,
            decision=decision,
        )
        if spec["termination_requested"]:
            session.metadata["terminated"] = True
            session.metadata["termination_reason"] = decision.reason
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)
        return self._materialize_policy_outcome_from_spec(
            session=session,
            plan=plan,
            decision=decision,
            spec=spec,
        )

    def _materialize_governed_tool_failure_outcome(self, *, session: ConversationSession, plan: ExecutionPlan, tool_request: ToolRequest, decision: PolicyDecision) -> ExecutionPlan:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        spec = ToolGovernanceService(self).build_policy_failure_outcome_spec(
            tool_request=tool_request,
            decision=decision,
        )
        invocation = ToolInvocation(
            run_id=session.conversation_id,
            step_id=f"session_turn:{session.session_id}",
            tool_name=tool_request.tool_name,
            input_payload=tool_request.input_payload,
            status=ToolInvocationStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            side_effect_class=tool_request.side_effect_class,
            result_payload=spec["invocation_failure_payload"],
        )
        self.store.save_tool_invocation(invocation)
        return self._materialize_policy_outcome_from_spec(
            session=session,
            plan=plan,
            decision=decision,
            spec=spec,
        )

    def _get_tool_governance_metadata(self, tool_name: str) -> dict[str, str]:
        tool = self.tool_registry.get(tool_name)
        if hasattr(tool, "governance_metadata"):
            return tool.governance_metadata()
        return {
            "policy_group": getattr(tool, "governance_policy_group", "system_environment"),
            "environment_check_kind": getattr(tool, "environment_check_kind", "none"),
        }

    def _mark_permission_authority_rejection(self, *, session: ConversationSession, tool_name: str) -> None:
        from orbit.runtime.governance.tool_governance_service import ToolGovernanceService

        ToolGovernanceService(self).mark_permission_rejection(session=session, tool_name=tool_name)

    def _get_pending_approval(self, session: ConversationSession) -> dict | None:
        pending = session.metadata.get("pending_approval")
        return pending if isinstance(pending, dict) else None

    def _plan_from_messages(self, *, session: ConversationSession, messages: list[ConversationMessage], on_assistant_partial_text=None, on_stream_completed=None) -> ExecutionPlan:
        """Use history-aware provider path when available, otherwise fallback."""
        if hasattr(self.backend, "plan_from_messages"):
            return self.backend.plan_from_messages(messages, session=session, on_partial_text=on_assistant_partial_text, on_stream_completed=on_stream_completed)
        latest_user = next((message for message in reversed(messages) if message.role == MessageRole.USER), None)
        if latest_user is None:
            raise ValueError("cannot fallback to descriptor path without a user message")
        mode_policy = session.metadata.get("mode_policy") if isinstance(session.metadata, dict) else None
        descriptor = RunDescriptor(
            session_key=f"session:{session.session_id}",
            conversation_id=session.conversation_id,
            runtime_mode=session.runtime_mode,
            mode_policy=ModePolicyDescriptor(**mode_policy) if isinstance(mode_policy, dict) else ModePolicyDescriptor(),
            workspace=WorkspaceDescriptor(cwd=self.workspace_root, writable_roots=[self.workspace_root]),
            user_input=latest_user.content,
        )
        return self.backend.plan(descriptor)
