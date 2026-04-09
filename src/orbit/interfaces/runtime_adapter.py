
from __future__ import annotations

from dataclasses import dataclass, field
import json
import sys
import time
from typing import Any

from orbit.interfaces.pty_debug import debug_log

from orbit.runtime.core.session_manager import SESSION_MANAGER_IMPORT_PROFILE_TIMINGS, SessionManager
from orbit.runtime.operations.context_usage_service import ContextAccountingService
from orbit.runtime.capabilities.composer import RuntimeCapabilityBundle, RuntimeCapabilityComposer, RuntimeCapabilityProfile
from orbit.runtime.governance.build_state_store import BuildStateStore
from orbit.runtime.governance.protocol.mode import RuntimeMode, build_policy_profile_for_mode, mode_policy_summary, workspace_root_for_runtime_mode
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.runtime.providers.openai_codex import OpenAICodexConfig, OpenAICodexExecutionBackend
from orbit.runtime.extensions.auxiliary_input import DetachedKnowledgeMemoryCollector
from orbit.runtime.extensions.post_turn_observer import DetachedMemoryCaptureObserver, NoOpPostTurnObserver
from orbit.runtime.extensions.capability_attach import RuntimeCoreMinimalCapabilityPolicy
from orbit.runtime.extensions.capability_surface import CapabilitySurfaceRunner, NoOpCapabilitySurface, RegistryBackedCapabilitySurface
from orbit.runtime.extensions.metadata_channels import capability_metadata, core_runtime_metadata, observer_metadata, operation_metadata, surface_projection_metadata
from orbit.settings import REPO_ROOT
from orbit.store import create_default_store

RUNTIME_ADAPTER_IMPORT_PROFILE_TIMINGS: dict[str, float] = {}
SESSION_MANAGER_IMPORT_PROFILE_TIMINGS = dict(SESSION_MANAGER_IMPORT_PROFILE_TIMINGS)

from .adapter_protocol import RuntimeCliAdapter
from .contracts import (
    InterfaceApproval,
    InterfaceArtifact,
    InterfaceEvent,
    InterfaceMessage,
    InterfaceSession,
    InterfaceToolCall,
    InterfaceToolDescriptor,
)


@dataclass
class RuntimeAdapterConfig:
    model: str = "gpt-5.4"
    runtime_mode: RuntimeMode = "dev"
    runtime_profile: str = "runtime_core_minimal"
    enable_tools: bool = True
    filesystem: bool = False
    git: bool = False
    bash: bool = False
    process: bool = False
    pytest: bool = False
    ruff: bool = False
    mypy: bool = False
    browser: bool = False
    obsidian: bool = False
    memory: bool = False


def build_codex_session_manager(*, model: str, runtime_mode: RuntimeMode = "dev", runtime_profile: str = "runtime_core_minimal", enable_tools: bool = True, filesystem: bool = False, git: bool = False, bash: bool = False, process: bool = False, pytest: bool = False, ruff: bool = False, mypy: bool = False, browser: bool = False, obsidian: bool = False, memory: bool = False) -> tuple[SessionManager, RuntimeCapabilityComposer, RuntimeCapabilityBundle]:
    t0 = time.perf_counter()
    workspace_root = workspace_root_for_runtime_mode(runtime_mode)
    t1 = time.perf_counter()
    store = create_default_store()
    backend = OpenAICodexExecutionBackend(
        config=OpenAICodexConfig(model=model, enable_tools=enable_tools),
        repo_root=REPO_ROOT,
        workspace_root=workspace_root,
    )
    setattr(backend, 'store', store)
    backend.auxiliary_input_collector = DetachedKnowledgeMemoryCollector(
        enable_knowledge=False,
        enable_memory=False,
        memory_service=None,
        session_manager=None,
    )
    t2 = time.perf_counter()
    profile = RuntimeCapabilityProfile(
        filesystem=filesystem,
        git=git,
        bash=bash,
        process=process,
        pytest=pytest,
        ruff=ruff,
        mypy=mypy,
        browser=browser,
        obsidian=obsidian,
        memory=memory,
    )
    composer = RuntimeCapabilityComposer(workspace_root=str(workspace_root), backend=backend)
    bundle = composer.activate(profile)
    t3 = time.perf_counter()
    manager = SessionManager(
        store=store,
        backend=backend,
        workspace_root=str(workspace_root),
        runtime_mode=runtime_mode,
    )
    manager.minimal_runtime_core = runtime_profile == "runtime_core_minimal"
    manager.capability_surface = RegistryBackedCapabilitySurface(
        tool_registry=bundle.tool_registry,
        capability_tool_registry=bundle.capability_tool_registry,
        enabled_capabilities=bundle.enabled_capabilities,
    )
    manager.post_turn_observer = NoOpPostTurnObserver()
    if hasattr(backend, "session_manager"):
        backend.session_manager = manager
    if hasattr(backend, "auxiliary_input_collector") and hasattr(backend.auxiliary_input_collector, "session_manager"):
        backend.auxiliary_input_collector.session_manager = manager
    if hasattr(backend, "auxiliary_input_collector") and hasattr(backend.auxiliary_input_collector, "memory_service"):
        backend.auxiliary_input_collector.memory_service = bundle.memory_service
    manager.post_turn_observer = DetachedMemoryCaptureObserver(memory_service=None)
    t4 = time.perf_counter()
    manager.metadata = {
        **getattr(manager, 'metadata', {}),
        "runtime_profile": runtime_profile,
        "build_profile_timings": {
            "workspace_select_ms": round((t1 - t0) * 1000, 2),
            "backend_init_ms": round((t2 - t1) * 1000, 2),
            "capability_activate_ms": round((t3 - t2) * 1000, 2),
            "session_manager_init_ms": round((t4 - t3) * 1000, 2),
            "total_ms": round((t4 - t0) * 1000, 2),
        },
        "capability_activation_metrics": dict(bundle.activation_metrics),
    }
    return manager, composer, bundle


def get_pending_session_approval(session_manager: SessionManager, session_id: str) -> dict | None:
    session = session_manager.get_session(session_id)
    if session is None or not isinstance(session.metadata, dict):
        return None
    pending = capability_metadata(session.metadata).get("pending_approval")
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
    def warmup_post_composer_capabilities(self) -> dict[str, float]:
        if self.capability_composer is None or self.capability_bundle is None:
            return {}
        timings = self.capability_composer.warmup(self.capability_bundle)
        self.startup_metrics.update(timings)
        self.session_manager.metadata = {
            **getattr(self.session_manager, 'metadata', {}),
            'capability_warmup_metrics': dict(timings),
        }
        return timings


    def __init__(self, session_manager: SessionManager, *, capability_composer: RuntimeCapabilityComposer | None = None, capability_bundle: RuntimeCapabilityBundle | None = None, build_state_store: BuildStateStore | None = None, startup_metrics: dict[str, float] | None = None) -> None:
        self.session_manager = session_manager
        self.capability_composer = capability_composer
        self.capability_bundle = capability_bundle
        self.build_state_store = build_state_store or BuildStateStore()
        self.startup_metrics = startup_metrics or {}
        self.capability_runner = CapabilitySurfaceRunner(
            session_manager=session_manager,
            capability_surface=session_manager.capability_surface,
        )
        self.session_manager.capability_handoff_dispatcher = self.capability_runner.consume_handoff_async

    @classmethod
    def build(cls, config: RuntimeAdapterConfig | None = None) -> "SessionManagerRuntimeAdapter":
        config = config or RuntimeAdapterConfig()
        t0 = time.perf_counter()
        session_manager, capability_composer, capability_bundle = build_codex_session_manager(
            model=config.model,
            runtime_mode=config.runtime_mode,
            runtime_profile=config.runtime_profile,
            enable_tools=config.enable_tools,
            filesystem=config.filesystem,
            git=config.git,
            bash=config.bash,
            process=config.process,
            pytest=config.pytest,
            ruff=config.ruff,
            mypy=config.mypy,
            browser=config.browser,
            obsidian=config.obsidian,
            memory=config.memory,
        )
        t1 = time.perf_counter()
        build_state_store = BuildStateStore()
        t2 = time.perf_counter()
        return cls(
            session_manager,
            capability_composer=capability_composer,
            capability_bundle=capability_bundle,
            build_state_store=build_state_store,
            startup_metrics={
                'session_manager_build_ms': round((t1 - t0) * 1000, 2),
                'build_state_store_init_ms': round((t2 - t1) * 1000, 2),
                'runtime_adapter_build_total_ms': round((t2 - t0) * 1000, 2),
            },
        )

    def create_session(self, *, backend_name: str = "openai-codex", model: str | None = None, runtime_mode: RuntimeMode | None = None) -> InterfaceSession:
        session = self.session_manager.create_session(
            backend_name=backend_name,
            model=model or getattr(self.session_manager.backend.config, "model", "gpt-5.4"),
            runtime_mode=runtime_mode or self.session_manager.runtime_mode,
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
        items: list[InterfaceArtifact] = []
        list_artifacts_fn = getattr(self.session_manager.store, "list_context_artifacts_for_run", None)
        if callable(list_artifacts_fn):
            artifacts = list_artifacts_fn(session.conversation_id)
            items.extend(
                InterfaceArtifact(
                    session_id=session_id,
                    artifact_type=artifact.artifact_type,
                    source=artifact.source,
                    content=artifact.content,
                )
                for artifact in artifacts
            )
        metadata_items = session.metadata.get("interface_artifacts", []) if isinstance(session.metadata, dict) else []
        if isinstance(metadata_items, list):
            items.extend(
                InterfaceArtifact(
                    session_id=session_id,
                    artifact_type=str(item.get("artifact_type") or "unknown_artifact"),
                    source=str(item.get("source") or "interface_metadata"),
                    content=str(item.get("content") or ""),
                )
                for item in metadata_items
                if isinstance(item, dict)
            )
        return items

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

    def list_available_tools(self) -> list[InterfaceToolDescriptor]:
        registry = getattr(self.capability_bundle, "capability_tool_registry", None)
        if registry is None:
            return []
        return [
            InterfaceToolDescriptor(
                tool_name=item.name,
                side_effect_class=item.side_effect_class,
                requires_approval=item.requires_approval,
                source=item.source,
                metadata=item.metadata,
            )
            for item in registry.list_tool_descriptors()
        ]

    def list_open_approvals(self) -> list[InterfaceApproval]:
        approvals = self.session_manager.list_open_session_approvals()
        return [self._map_open_approval(item) for item in approvals]

    def send_user_message(self, session_id: str, text: str, on_assistant_partial_text=None, on_stream_completed=None) -> list[InterfaceMessage]:
        started_at = time.perf_counter()
        try:
            self.session_manager.run_session_turn(session_id=session_id, user_input=text, on_assistant_partial_text=on_assistant_partial_text, on_stream_completed=on_stream_completed)
        finally:
            try:
                debug_log(
                    "runtime_adapter:send_user_message "
                    + json.dumps(
                        {
                            "session_id": session_id,
                            "text_len": len(text),
                            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception:
                pass
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
            "/i /chat /approvals /events /tools /artifacts /status /self-audit /pending /approve /reject /wipe-history"
        )

    def slash_help_page(self) -> str:
        return "\n".join(
            [
                "ORBIT Slash Help",
                "",
                "Slash commands",
                "/help /new /sessions /attach <session_id> /detach",
                "/chat /i /events /tools /artifacts /approvals /status /self-audit",
                "/pending /approve [note] /reject [note]",
                "/show /state /clear /clear-all /wipe-history",
                "",
                "/i opens inspect mode.",
                "/wipe-history clears ORBIT session/chat history from the SQLite store.",
                "It does not clear the separate process runtime database.",
            ]
        )

    def get_context_usage_projection(self, session_id: str) -> dict[str, Any]:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return {"latest_call": None, "totals": {"total_input_tokens": 0, "total_output_tokens": 0, "total_cache_creation_input_tokens": 0, "total_cache_read_input_tokens": 0, "total_reasoning_tokens": 0, "call_count": 0}}
        operation_channel = operation_metadata(session.metadata) if isinstance(session.metadata, dict) else {}
        usage_projection = operation_channel.get("usage_projection") if isinstance(operation_channel.get("usage_projection"), dict) else None
        if usage_projection is not None:
            return usage_projection
        return {"latest_call": None, "totals": {"total_input_tokens": 0, "total_output_tokens": 0, "total_cache_creation_input_tokens": 0, "total_cache_read_input_tokens": 0, "total_reasoning_tokens": 0, "call_count": 0}}

    def get_workbench_status(self) -> dict[str, Any]:
        sessions = self.list_sessions()
        runtime_profile = getattr(self.session_manager, 'metadata', {}).get('runtime_profile', 'runtime_core_minimal')
        tool_names = []
        capability_surface_snapshot = None
        policy = mode_policy_summary(self.session_manager.runtime_mode)
        activation = self.build_state_store.load_activation_pointer()
        metadata = getattr(self.session_manager, 'metadata', {}) if hasattr(self.session_manager, 'metadata') else {}
        profile_timings = metadata.get('build_profile_timings', {})
        session_manager_profile_timings = metadata.get('session_manager_profile_timings', {})
        runtime_mode = self.session_manager.runtime_mode
        build_policy_profile = build_policy_profile_for_mode(runtime_mode)
        active_self_change_plan_ids = [s.active_self_change_plan_id for s in sessions if s.active_self_change_plan_id]
        active_build_record_ids = [s.active_build_record_id for s in sessions if s.active_build_record_id]
        last_build_statuses = [s.last_build_status for s in sessions if s.last_build_status]
        session_usage_projections: dict[str, Any] = {
            session.session_id: self.get_context_usage_projection(session.session_id)
            for session in sessions
        }
        active_continuation_sessions = []
        continuation_transition_overview = []
        for session in sessions:
            operation_channel = getattr(session, "operation_channel", {}) or {}
            session_activity = operation_channel.get("session_activity")
            if session_activity and session_activity != "idle":
                active_continuation_sessions.append(
                    {
                        "session_id": session.session_id,
                        "status": session.status,
                        "session_activity": session_activity,
                        "active_continuation": operation_channel.get("active_continuation"),
                    }
                )
            transition_log = operation_channel.get("continuation_transition_log")
            if isinstance(transition_log, list) and transition_log:
                continuation_transition_overview.append(
                    {
                        "session_id": session.session_id,
                        "latest_transition": transition_log[-1],
                        "transition_count": len(transition_log),
                    }
                )
        available_tools = [tool.model_dump(mode="json") for tool in self.list_available_tools()]
        return {
            "adapter_kind": "session_manager_runtime",
            "runtime_mode": runtime_mode,
            "runtime_profile": metadata.get("runtime_profile", "runtime_core_minimal"),
            "minimal_runtime_core": bool(getattr(self.session_manager, "minimal_runtime_core", False)),
            "capability_surface": capability_surface_snapshot.metadata if capability_surface_snapshot is not None else {"surface_state": "unbound"},
            "workspace_root": self.session_manager.workspace_root,
            **policy,
            "build_profile_timings": profile_timings,
            "session_manager_profile_timings": session_manager_profile_timings,
            "startup_metrics": {},
            "active_build_id": activation.active_build_id,
            "candidate_build_id": activation.candidate_build_id,
            "last_known_good_build_id": activation.last_known_good_build_id,
            "session_count": len(sessions),
            "approval_count": 0,
            "registered_tool_count": len(available_tools),
            "registered_tool_names": [tool["tool_name"] for tool in available_tools],
            "available_tools": available_tools,
            "build_policy_profile": build_policy_profile,
            "active_self_change_plan_ids": active_self_change_plan_ids,
            "active_build_record_ids": active_build_record_ids,
            "last_build_statuses": last_build_statuses,
            "session_usage_projections": session_usage_projections,
            "active_continuation_sessions": active_continuation_sessions,
            "continuation_transition_overview": continuation_transition_overview,
        }

    def get_pending_approval(self, session_id: str) -> InterfaceApproval | None:
        return None

    def resolve_pending_approval(self, session_id: str, decision: str, note: str | None = None):
        return None

    def reauthorize_tool_path(self, session_id: str, tool_name: str, note: str | None = None, source: str = "runtime_cli"):
        return None

    def get_session_state_payload(self, session_id: str) -> dict[str, Any] | None:
        session = self.session_manager.get_session(session_id)
        if session is None:
            return None
        return session.model_dump(mode="json")

    def append_context_artifact(self, session_id: str, artifact_type: str, content: str, source: str):
        artifact = self.session_manager.append_context_artifact_for_session(
            session_id=session_id,
            artifact_type=artifact_type,
            content=content,
            source=source,
        )
        session = self.session_manager.get_session(session_id)
        if artifact is not None and session is not None and isinstance(session.metadata, dict):
            session.metadata.setdefault("interface_artifacts", []).append(
                {
                    "artifact_type": artifact_type,
                    "source": source,
                    "content": content,
                }
            )
            self.session_manager.store.save_session(session)
        return artifact

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

    def wipe_session_history(self) -> bool:
        return self.clear_all_sessions()

    def _extract_build_projection(self, session) -> dict[str, Any]:
        meta = session.metadata if isinstance(session.metadata, dict) else {}
        sc = meta.get("self_change", {}) if isinstance(meta.get("self_change"), dict) else {}
        bm = meta.get("build_management", {}) if isinstance(meta.get("build_management"), dict) else {}
        last_build = bm.get("last_build", {}) if isinstance(bm.get("last_build"), dict) else {}
        mode = getattr(session, "runtime_mode", "dev")
        policy = mode_policy_summary(mode)
        build_policy = build_policy_profile_for_mode(mode)
        return {
            "active_self_change_plan_id": sc.get("active_plan_id"),
            "active_build_record_id": bm.get("active_build_id"),
            "last_build_status": last_build.get("status"),
            "last_build_summary": last_build.get("summary"),
            "build_policy_profile": build_policy,
        }

    def _diagnose_operation_channel(self, session, *, operation_channel: dict | None = None) -> dict[str, Any]:
        operation_channel = operation_channel if isinstance(operation_channel, dict) else (operation_metadata(session.metadata) if isinstance(session.metadata, dict) else {})
        active = operation_channel.get("active_continuation") if isinstance(operation_channel, dict) else None
        diagnosis: dict[str, Any] = {
            "session_activity": operation_channel.get("session_activity") if isinstance(operation_channel, dict) else None,
            "orphaned": False,
            "stale_view": False,
            "recommended_action": None,
        }
        if not isinstance(active, dict):
            return diagnosis
        continuation_state = active.get("continuation_state")
        messages = self.session_manager.list_messages(session.session_id)
        has_assistant = any(getattr(message.role, "value", str(message.role)) == "assistant" for message in messages)
        if continuation_state == "result_ingested" and has_assistant:
            diagnosis["stale_view"] = True
            diagnosis["recommended_action"] = "operation_view_should_treat_as_settled"
        elif continuation_state == "awaiting_capability_result":
            diagnosis["orphaned"] = True
            diagnosis["recommended_action"] = "inspect_or_resume_capability_runner"
        return diagnosis

    def _map_session_summary(self, session) -> InterfaceSession:
        policy = mode_policy_summary(session.runtime_mode)
        build = self._extract_build_projection(session)
        operation_channel = operation_metadata(session.metadata) if isinstance(session.metadata, dict) else {}
        diagnosis = self._diagnose_operation_channel(session, operation_channel=operation_channel)
        session_activity = diagnosis.get("session_activity")
        status = "active"
        if session_activity == "continuation_pending":
            status = "active_continuation"
        elif session_activity == "continuation_reopening_turn":
            status = "continuation_reopening_turn"
        elif session_activity == "continuation_discarded":
            status = "continuation_discarded"
        return InterfaceSession(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            backend_name=session.backend_name,
            model=session.model,
            runtime_mode=session.runtime_mode,
            workspace_root=self.session_manager.workspace_root,
            mode_policy_profile=policy["mode_policy_profile"],
            self_runtime_visibility=policy["self_runtime_visibility"],
            self_modification_posture=policy["self_modification_posture"],
            updated_at=session.updated_at,
            message_count=0,
            last_message_preview="",
            status=status,
            operation_channel={**operation_channel, "diagnosis": diagnosis},
            **build,
        )

    def _map_session(self, session) -> InterfaceSession:
        messages = self.session_manager.list_messages(session.session_id)
        last_message = messages[-1].content if messages else ""
        pending = self.get_pending_approval(session.session_id)
        operation_channel = operation_metadata(session.metadata) if isinstance(session.metadata, dict) else {}
        diagnosis = self._diagnose_operation_channel(session, operation_channel=operation_channel)
        status = "waiting_for_approval" if pending is not None else "active"
        session_activity = diagnosis.get("session_activity")
        if session_activity == "continuation_pending":
            status = "active_continuation"
        elif session_activity == "continuation_reopening_turn":
            status = "continuation_reopening_turn"
        elif session_activity == "continuation_discarded":
            status = "continuation_discarded"
        policy = mode_policy_summary(session.runtime_mode)
        build = self._extract_build_projection(session)
        return InterfaceSession(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            backend_name=session.backend_name,
            model=session.model,
            runtime_mode=session.runtime_mode,
            workspace_root=self.session_manager.workspace_root,
            mode_policy_profile=policy["mode_policy_profile"],
            self_runtime_visibility=policy["self_runtime_visibility"],
            self_modification_posture=policy["self_modification_posture"],
            updated_at=session.updated_at,
            message_count=len(messages),
            last_message_preview=last_message[:120],
            status=status,
            operation_channel={**operation_channel, "diagnosis": diagnosis},
            **build,
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
