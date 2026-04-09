
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.models.core import new_id
from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.extensions.metadata_channels import (
    capability_metadata,
    core_runtime_metadata,
    observer_metadata,
    operation_metadata,
    set_core_runtime_metadata,
)
from orbit.runtime.extensions.capability_attach import RuntimeCoreMinimalCapabilityPolicy
from orbit.runtime.core.continuation_planner import RuntimeContinuationPlanner
from orbit.runtime.core.outcomes import ResolvedRuntimeOutcome
from orbit.runtime.extensions.auxiliary_input import AuxiliaryInputCollection, NoOpAuxiliaryInputCollector
from orbit.runtime.extensions.capability_surface import NoOpCapabilitySurface
from orbit.runtime.governance.protocol.mode import ModePolicyDescriptor, RuntimeMode, build_mode_policy_snapshot
from orbit.runtime.execution.contracts.plans import ExecutionPlan
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.store.base import OrbitStore

SESSION_MANAGER_IMPORT_PROFILE_TIMINGS: dict[str, float] = {}


class SessionManager:

    def __init__(
        self,
        *,
        store: OrbitStore,
        backend,
        workspace_root: str,
        runtime_mode: RuntimeMode = "dev",
    ):
        t0 = time.perf_counter()
        self.store = store
        self.backend = backend
        self.workspace_root = workspace_root
        self.runtime_mode = runtime_mode
        self.metadata = {**getattr(self, 'metadata', {}), 'session_manager_profile_timings': {}}
        timings: dict[str, float] = self.metadata['session_manager_profile_timings']

        self.post_turn_observer = None
        self.auxiliary_input_collector = NoOpAuxiliaryInputCollector()
        self.capability_surface = NoOpCapabilitySurface()
        self.capability_handoff_dispatcher = None
        self.minimal_runtime_core = True
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

    def _run_post_turn_observer(self, *, session: ConversationSession, plan: ExecutionPlan, messages: list[ConversationMessage]) -> None:
        observer = getattr(self, "post_turn_observer", None)
        if observer is None:
            return
        result = observer.on_turn_completed(
            session=session,
            plan=plan,
            messages=messages,
            runtime_profile=getattr(self, "metadata", {}).get("runtime_profile", "runtime_core_minimal"),
        )
        if result is not None and isinstance(getattr(result, "metadata", None), dict) and result.metadata:
            observer_metadata(session.metadata).update(result.metadata)
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)

    def _collect_auxiliary_input(self, *, session: ConversationSession, messages: list[ConversationMessage]) -> AuxiliaryInputCollection:
        collector = getattr(self, "auxiliary_input_collector", None)
        if collector is None:
            return AuxiliaryInputCollection(fragments=[], metadata={}, timings={})
        latest_user = next((message for message in reversed(messages) if message.role == MessageRole.USER and message.content.strip()), None)
        query_text = latest_user.content if latest_user is not None else messages[-1].content if messages else ""
        auxiliary = collector.collect(
            session=session,
            messages=messages,
            runtime_profile=getattr(self, "metadata", {}).get("runtime_profile", "runtime_core_minimal"),
            query_text=query_text,
        )
        if isinstance(auxiliary.metadata, dict) and auxiliary.metadata:
            observer_metadata(session.metadata).update(auxiliary.metadata)
        if isinstance(auxiliary.timings, dict) and auxiliary.timings:
            operation_metadata(session.metadata)["auxiliary_input_timings"] = dict(auxiliary.timings)
        if auxiliary.metadata or auxiliary.timings:
            session.updated_at = datetime.now(timezone.utc)
            self.store.save_session(session)
        return auxiliary

    def set_active_run_descriptor(self, *, session_id: str, descriptor: RunDescriptor) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        set_core_runtime_metadata(session.metadata, "active_run_descriptor", descriptor.model_dump(mode="json"))
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)

    def run_session_turn(self, *, session_id: str, user_input: str, descriptor: RunDescriptor | None = None, on_assistant_partial_text=None, on_stream_completed=None) -> ExecutionPlan:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        if core_runtime_metadata(session.metadata).get("terminated"):
            raise ValueError(f"session terminated: {session_id}")
        if descriptor is not None:
            self.set_active_run_descriptor(session_id=session_id, descriptor=descriptor)
            refreshed = self.get_session(session_id)
            if refreshed is None:
                raise ValueError(f"session not found after recording run descriptor: {session_id}")
            session = refreshed
        self.append_message(session_id=session_id, role=MessageRole.USER, content=user_input)
        messages = self.list_messages(session_id)
        try:
            plan = self._plan_from_messages(session=session, messages=messages, on_assistant_partial_text=on_assistant_partial_text, on_stream_completed=on_stream_completed)
        except OpenAIAuthStoreError as exc:
            failure_message = str(exc)
            return ExecutionPlan(
                source_backend=getattr(self.backend, "backend_name", session.backend_name),
                plan_label="auth-failure",
                failure_reason=failure_message,
            )
        return self._finalize_session_plan(session=session, plan=plan, messages=messages)

    def _materialize_non_tool_terminal_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:
        if plan.failure_reason:
            self.append_message(
                session_id=session.session_id,
                role=MessageRole.ASSISTANT,
                content=plan.failure_reason,
                metadata={
                    "message_kind": "runtime_failure",
                    "source_backend": plan.source_backend,
                    "plan_label": plan.plan_label,
                    "failure_reason": plan.failure_reason,
                },
            )
            return plan
        self.append_message(
            session_id=session.session_id,
            role=MessageRole.ASSISTANT,
            content=plan.final_text,
            metadata={"source_backend": plan.source_backend, "plan_label": plan.plan_label},
        )
        refreshed = self.get_session(session.session_id)
        if refreshed is not None:
            self._run_post_turn_observer(session=refreshed, plan=plan, messages=self.list_messages(session.session_id))
        return plan

    def _materialize_tool_request_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:
        RuntimeCoreMinimalCapabilityPolicy().decide(
            session=session,
            plan=plan,
            runtime_profile="runtime_core_minimal",
        )
        handoff = self.capability_surface.submit_handoff(
            session=session,
            plan=plan,
            runtime_profile="runtime_core_minimal",
        )
        handoff_messages = self.list_messages(session.session_id)
        capability_state = capability_metadata(session.metadata)
        pending_handoff = capability_state.get("pending_handoff", {})
        continuation = {
            **pending_handoff,
            "capability_request_id": handoff.capability_request_id,
            "acceptance_turn_index": len(handoff_messages),
            "status": handoff.status,
            "continuation_state": "awaiting_capability_result",
            "session_turn_state": "turn_closed_continuation_pending",
            "continuation_opened_at": datetime.now(timezone.utc).isoformat(),
        }
        capability_state["pending_handoff"] = continuation
        capability_state["active_continuation"] = continuation
        operation_state = operation_metadata(session.metadata)
        operation_state["active_continuation"] = continuation
        operation_state["session_activity"] = "continuation_pending"
        operation_state["continuation_transition_log"] = [
            {
                "state": "continuation_pending",
                "capability_request_id": handoff.capability_request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)
        detached = ExecutionPlan(
            source_backend=plan.source_backend,
            plan_label=f"{plan.plan_label}-tool-request-handoff",
            final_text=handoff.message,
            should_finish_after_tool=True,
        )
        self.append_message(
            session_id=session.session_id,
            role=MessageRole.ASSISTANT,
            content=detached.final_text,
            metadata={
                "message_kind": "tool_request_handoff",
                "source_backend": plan.source_backend,
                "plan_label": detached.plan_label,
                "capability_request_id": handoff.capability_request_id,
                "capability_status": handoff.status,
                "provider_call_id": continuation.get("provider_call_id"),
                "tool_name": plan.tool_request.tool_name if plan.tool_request else None,
                "input_payload": plan.tool_request.input_payload if plan.tool_request else None,
                "tool_projection": handoff.tool_projection,
            },
        )
        refreshed = self.get_session(session.session_id)
        if refreshed is not None:
            self._run_post_turn_observer(session=refreshed, plan=detached, messages=self.list_messages(session.session_id))
        dispatcher = getattr(self, "capability_handoff_dispatcher", None)
        if callable(dispatcher):
            dispatcher(session_id=session.session_id, capability_request_id=handoff.capability_request_id)
        return detached

    def _finalize_session_plan(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
    ) -> ExecutionPlan:
        if plan.tool_request is not None:
            return self._materialize_tool_request_plan(
                session=session,
                plan=plan,
            )
        return self._materialize_non_tool_terminal_plan(
            session=session,
            plan=plan,
        )


    def _apply_canonical_mutations(self, *, session: ConversationSession, mutations: list[dict[str, Any]]) -> dict[str, Any]:
        operation_state = operation_metadata(session.metadata)
        for mutation in mutations:
            kind = mutation.get("kind")
            target_info = mutation.get("target") if isinstance(mutation.get("target"), dict) else {}
            scope = target_info.get("scope")
            key = target_info.get("key")
            value = mutation.get("value")
            if scope == "capability_metadata" and isinstance(key, str):
                bucket = capability_metadata(session.metadata)
                current = bucket.get(key)
                target_mutation_id = target_info.get("target_id")
                if kind == "merge_dict" and isinstance(value, dict) and isinstance(current, dict) and current.get("capability_request_id") == target_mutation_id:
                    current.update(value)
                elif kind == "set_dict" and isinstance(value, dict):
                    bucket[key] = value
            elif scope == "operation_metadata" and isinstance(key, str):
                if kind == "set_scalar":
                    operation_state[key] = value
                elif kind == "set_dict" and isinstance(value, dict):
                    operation_state[key] = value
        session.updated_at = datetime.now(timezone.utc)
        self.store.save_session(session)
        return operation_state

    def apply_runtime_outcome(
        self,
        *,
        session_id: str,
        outcome: ResolvedRuntimeOutcome,
    ) -> ExecutionPlan | None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        target = outcome.resolved_target
        target_id = target.target_id
        if target.target_kind != "capability_handoff":
            raise ValueError(f"unsupported resolved runtime outcome target: {target}")
        pending_key = str(target.anchor_handle.get("pending_key") or "pending_handoff")
        pending = capability_metadata(session.metadata).get(pending_key)
        if not isinstance(pending, dict) or pending.get("capability_request_id") != target_id:
            raise ValueError(f"pending runtime outcome target not found: {target}")
        operation_state = self._apply_canonical_mutations(session=session, mutations=outcome.canonical_mutations)
        transcript_entry = outcome.transcript_entry if isinstance(outcome.transcript_entry, dict) else None
        if outcome.continuation_directive.append_transcript and transcript_entry is not None:
            self.append_message(
                session_id=session_id,
                role=transcript_entry.get("role", MessageRole.TOOL),
                content=transcript_entry.get("content", outcome.content),
                metadata=transcript_entry.get("metadata", {}),
            )
        if outcome.continuation_directive.kind == "hold":
            session = self.get_session(session_id)
            if session is not None and operation_state.get("session_activity") != "waiting_for_approval":
                operation_state = operation_metadata(session.metadata)
                operation_state["session_activity"] = outcome.continuation_directive.activity or "paused"
                session.updated_at = datetime.now(timezone.utc)
                self.store.save_session(session)
            return None
        return self._continue_runtime_outcome_from_target(
            session_id=session_id,
            target=target,
            result_text=outcome.content,
        )

    def _continue_runtime_outcome_from_target(
        self,
        *,
        session_id: str,
        target,
        result_text: str,
    ) -> ExecutionPlan | None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        target_id = target.target_id
        pending_key = str(target.anchor_handle.get("pending_key") or "pending_handoff")
        active_key = str(target.anchor_handle.get("active_key") or "active_continuation")
        pending = capability_metadata(session.metadata).get(pending_key) if isinstance(session.metadata, dict) else None
        if not isinstance(pending, dict):
            return None
        active_continuation = capability_metadata(session.metadata).get(active_key)
        if pending.get("capability_request_id") != target_id:
            return None
        if not isinstance(active_continuation, dict):
            return None
        if active_continuation.get("capability_request_id") != target_id:
            return None
        # Snapshot provider_call_id before canonical mutations can mutate pending.
        snapshot_provider_call_id = pending.get("provider_call_id")
        snapshot_tool_projection = dict(pending.get("tool_projection") or {})
        messages = self.list_messages(session_id)
        continuation_plan = RuntimeContinuationPlanner().build(
            target=target,
            messages=messages,
            pending=pending,
        )
        if continuation_plan.stale:
            self._apply_canonical_mutations(session=session, mutations=continuation_plan.mutations_on_stale)
            return None
        self._apply_canonical_mutations(session=session, mutations=continuation_plan.mutations_before_continue)
        self.append_message(
            session_id=session_id,
            role=MessageRole.TOOL,
            content=result_text,
            metadata={
                "message_kind": "capability_result",
                "capability_request_id": target_id,
                "provider_call_id": snapshot_provider_call_id,
                "tool_projection": snapshot_tool_projection,
            },
        )
        refreshed = self.get_session(session_id)
        if refreshed is None:
            raise ValueError(f"session not found after capability result ingest: {session_id}")
        messages = self.list_messages(session_id)
        plan = self._plan_from_messages(session=refreshed, messages=messages)
        finalized = self._finalize_session_plan(session=refreshed, plan=plan, messages=messages)
        settled = self.get_session(session_id)
        if settled is not None:
            settled_capability = capability_metadata(settled.metadata)
            active = settled_capability.get(active_key)
            if isinstance(active, dict) and active.get("capability_request_id") == target_id:
                self._apply_canonical_mutations(session=settled, mutations=continuation_plan.mutations_after_settle)
        return finalized

    def _plan_from_messages(self, *, session: ConversationSession, messages: list[ConversationMessage], on_assistant_partial_text=None, on_stream_completed=None) -> ExecutionPlan:
        auxiliary = self._collect_auxiliary_input(session=session, messages=messages)
        if hasattr(self.backend, "plan_from_messages"):
            return self.backend.plan_from_messages(
                messages,
                session=session,
                auxiliary_fragments=auxiliary.fragments,
                on_partial_text=on_assistant_partial_text,
                on_stream_completed=on_stream_completed,
            )
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
