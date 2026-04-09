
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Callable

from orbit.interfaces.pty_debug import debug_log

from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential, ResolvedOpenAIAuthMaterial, resolve_openai_auth_material
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore
from orbit.runtime.execution.backends import ExecutionBackend
from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.execution.context_assembly import build_text_only_prompt_assembly_plan
from orbit.runtime.execution.transcript_projection import messages_to_codex_input
from orbit.runtime.extensions.auxiliary_input import DetachedKnowledgeMemoryCollector, NoOpAuxiliaryInputCollector
from orbit.runtime.extensions.capability_registry import CapabilityToolRegistry, RegistryBackedCapabilityToolRegistry
from orbit.runtime.extensions.metadata_channels import observer_metadata, operation_metadata, set_surface_projection_metadata, surface_projection_metadata
from orbit.runtime.operations.context_usage_service import ContextAccountingService
from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_server, bootstrap_local_git_mcp_server
from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.runtime.transports.openai_codex_http import OpenAICodexHttpError, OpenAICodexSSEEvent, stream_sse_events
from orbit.tools.registry import ToolRegistry
from orbit.runtime.providers.tool_schema_utils import codex_function_definition

OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"


@dataclass
class OpenAICodexConfig:
    model: str = "gpt-5.4"
    api_base: str = OPENAI_CODEX_BASE_URL
    timeout_seconds: int = 60
    enable_tools: bool = True


class OpenAICodexExecutionBackend(ExecutionBackend):
    backend_name = "openai-codex"

    def _knowledge_enabled(self) -> bool:
        raw = os.environ.get("ORBIT_ENABLE_KNOWLEDGE", "0").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def __init__(self, config: OpenAICodexConfig | None = None, repo_root: Path | None = None, workspace_root: Path | None = None, tool_registry: ToolRegistry | None = None, capability_tool_registry: CapabilityToolRegistry | None = None):
        self.config = config or OpenAICodexConfig()
        self.repo_root = repo_root or Path.cwd()
        self.workspace_root = workspace_root or self.repo_root
        self.auth_store = OpenAIAuthStore(self.repo_root)
        self.tool_registry = tool_registry
        self.capability_tool_registry = capability_tool_registry
        self.auxiliary_input_collector = NoOpAuxiliaryInputCollector()

    def _effective_tool_registry(self) -> ToolRegistry:
        if self.tool_registry is not None:
            return self.tool_registry
        registry = ToolRegistry(self.workspace_root)
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_filesystem_mcp_server(workspace_root=str(self.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_git_mcp_server(workspace_root=str(self.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_bash_mcp_server(workspace_root=str(self.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_process_mcp_server(workspace_root=str(self.workspace_root)),
        )
        self.tool_registry = registry
        self.capability_tool_registry = RegistryBackedCapabilityToolRegistry(tool_registry=registry)
        return registry

    def _effective_capability_tool_registry(self) -> CapabilityToolRegistry:
        if self.capability_tool_registry is not None:
            return self.capability_tool_registry
        registry = self._effective_tool_registry()
        self.capability_tool_registry = RegistryBackedCapabilityToolRegistry(tool_registry=registry)
        return self.capability_tool_registry

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        return self.plan_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def plan_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None, on_partial_text: Callable[[str], None] | None = None, on_stream_completed: Callable[[], None] | None = None) -> ExecutionPlan:
        total_started_at = time.perf_counter()
        auth_started_at = time.perf_counter()
        credential = self.load_persisted_credential()
        auth = self.resolve_auth_material(credential)
        url = self.build_request_url()
        headers = self.build_request_headers(auth)
        auth_elapsed_ms = round((time.perf_counter() - auth_started_at) * 1000, 2)
        payload_started_at = time.perf_counter()
        payload = self.build_request_payload_from_messages(messages, session=session)
        payload_elapsed_ms = round((time.perf_counter() - payload_started_at) * 1000, 2)
        if session is not None:
            set_surface_projection_metadata(session.metadata, "last_provider_payload", payload)
        try:
            events: list[OpenAICodexSSEEvent] = []
            accumulated_text_parts: list[str] = []
            stream_started_at = time.perf_counter()
            first_event_ms: float | None = None
            first_text_delta_ms: float | None = None
            for event in stream_sse_events(url=url, headers=headers, payload=payload, timeout_seconds=self.config.timeout_seconds):
                if first_event_ms is None:
                    first_event_ms = round((time.perf_counter() - stream_started_at) * 1000, 2)
                events.append(event)
                event_type = event.payload.get("type")
                if event_type == "response.output_text.delta":
                    if first_text_delta_ms is None:
                        first_text_delta_ms = round((time.perf_counter() - stream_started_at) * 1000, 2)
                    if on_partial_text is not None:
                        delta = event.payload.get("delta")
                        if isinstance(delta, str):
                            accumulated_text_parts.append(delta)
                            try:
                                on_partial_text("".join(accumulated_text_parts))
                            except Exception:
                                pass
            stream_elapsed_ms = round((time.perf_counter() - stream_started_at) * 1000, 2)
        except OpenAICodexHttpError as exc:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-transport-failure", failure=ProviderFailure(kind="transport_error", message=str(exc)), metadata={"payload_shape": "codex_messages_projection"})
            return normalized_result_to_execution_plan(normalized)
        if on_stream_completed is not None:
            try:
                on_stream_completed()
            except Exception:
                pass
        normalize_started_at = time.perf_counter()
        plan = self.normalize_events(events, on_partial_text=None)
        normalize_elapsed_ms = round((time.perf_counter() - normalize_started_at) * 1000, 2)
        try:
            debug_log(
                "openai_codex:plan_from_messages "
                + json.dumps(
                    {
                        "session_id": getattr(session, "session_id", None),
                        "message_count": len(messages),
                        "auth_ms": auth_elapsed_ms,
                        "payload_build_ms": payload_elapsed_ms,
                        "first_event_ms": first_event_ms,
                        "first_text_delta_ms": first_text_delta_ms,
                        "stream_ms": stream_elapsed_ms,
                        "normalize_ms": normalize_elapsed_ms,
                        "total_ms": round((time.perf_counter() - total_started_at) * 1000, 2),
                        "event_count": len(events),
                        "tool_count": len(payload.get("tools") or []),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
        if session is not None:
            usage_service = ContextAccountingService()
            call_usage = usage_service.normalize_provider_usage(
                usage=plan.metadata.get("usage") if isinstance(plan.metadata, dict) else None,
                provider=self.backend_name,
                model=self.config.model,
            )
            if call_usage is not None:
                usage_service.record_observed_usage(session=session, call_usage=call_usage, store=getattr(self, "store", None))
                operation_state = operation_metadata(session.metadata)
                operation_state["usage_projection"] = usage_service.build_status_projection(session=session)
                store = getattr(self, "store", None)
                if store is not None:
                    session.updated_at = datetime.now(timezone.utc)
                    store.save_session(session)
        return plan

    def load_persisted_credential(self) -> OpenAIOAuthCredential:
        return self.auth_store.load_fresh()

    def resolve_auth_material(self, credential: OpenAIOAuthCredential) -> ResolvedOpenAIAuthMaterial:
        return resolve_openai_auth_material(credential)

    def build_request_headers(self, auth: ResolvedOpenAIAuthMaterial) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.bearer_token}", "Content-Type": "application/json", "Accept": "text/event-stream"}

    def build_request_url(self) -> str:
        return self.config.api_base.rstrip("/") + "/codex/responses"

    def build_request_payload(self, descriptor: RunDescriptor) -> dict:
        return self.build_request_payload_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def build_tool_definitions(self) -> list[dict]:
        registry = self._effective_capability_tool_registry()
        return registry.build_provider_tool_definitions()

    def build_request_payload_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> dict:
        build_started_at = time.perf_counter()
        latest_user = next((message for message in reversed(messages) if message.role == MessageRole.USER and message.content.strip()), None)
        query_text = latest_user.content if latest_user is not None else messages[-1].content if messages else ""

        collector = getattr(self, "auxiliary_input_collector", None) or NoOpAuxiliaryInputCollector()
        auxiliary = collector.collect(
            session=session,
            messages=messages,
            runtime_profile=getattr(getattr(self, "session_manager", None), "metadata", {}).get("runtime_profile", "runtime_core_minimal") if session is not None else "runtime_core_minimal",
            query_text=query_text,
        )
        auxiliary_fragments = list(auxiliary.fragments)
        memory_retrieval_ms = auxiliary.timings.get("memory_retrieval_ms", 0.0)
        knowledge_setup_ms = auxiliary.timings.get("knowledge_setup_ms", 0.0)
        knowledge_preflight_ms = auxiliary.timings.get("knowledge_preflight_ms", 0.0)
        knowledge_retrieval_ms = auxiliary.timings.get("knowledge_retrieval_ms", 0.0)
        if session is not None and isinstance(auxiliary.metadata, dict):
            observer_metadata(session.metadata).update(auxiliary.metadata)
        runtime_mode = session.runtime_mode if session is not None else "dev"
        assembly_started_at = time.perf_counter()
        assembly_plan = build_text_only_prompt_assembly_plan(
            backend_name=self.backend_name,
            model=self.config.model,
            messages=messages,
            workspace_root=str(self.workspace_root),
            runtime_mode=runtime_mode,
            auxiliary_fragments=auxiliary_fragments,
        )
        assembly_plan_ms = round((time.perf_counter() - assembly_started_at) * 1000, 2)
        instructions = assembly_plan.effective_instructions
        transcript_projection_started_at = time.perf_counter()
        projected_input = messages_to_codex_input(messages)
        transcript_projection_ms = round((time.perf_counter() - transcript_projection_started_at) * 1000, 2)
        payload_dict_started_at = time.perf_counter()
        payload = {
            "model": self.config.model,
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": projected_input,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
        }
        payload_dict_ms = round((time.perf_counter() - payload_dict_started_at) * 1000, 2)
        tools = []
        if self.config.enable_tools:
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
            tools = self.build_tool_definitions()
            if tools:
                payload["tools"] = tools
        session_snapshot_write_ms = 0.0
        if session is not None:
            snapshot_write_started_at = time.perf_counter()
            snapshot = assembly_plan.to_snapshot_dict()
            snapshot["tooling"] = {
                "enable_tools": self.config.enable_tools,
                "tool_count": len(tools),
            }
            set_surface_projection_metadata(session.metadata, "_pending_context_assembly", snapshot)
            set_surface_projection_metadata(session.metadata, "_pending_provider_payload", payload.copy())
            payload["prompt_cache_key"] = session.session_id
            session_snapshot_write_ms = round((time.perf_counter() - snapshot_write_started_at) * 1000, 2)
            set_surface_projection_metadata(session.metadata, "last_submit_timing_probe", {
                "memory_retrieval_ms": memory_retrieval_ms,
                "knowledge_setup_ms": knowledge_setup_ms,
                "knowledge_preflight_ms": knowledge_preflight_ms,
                "knowledge_retrieval_ms": knowledge_retrieval_ms,
                "assembly_plan_ms": assembly_plan_ms,
                "transcript_projection_ms": transcript_projection_ms,
                "payload_dict_ms": payload_dict_ms,
                "session_snapshot_write_ms": session_snapshot_write_ms,
                "payload_build_total_ms": round((time.perf_counter() - build_started_at) * 1000, 2),
                "tool_count": len(tools),
            })
        try:
            debug_log(
                "openai_codex:build_request_payload "
                + json.dumps(
                    {
                        "session_id": getattr(session, "session_id", None),
                        "message_count": len(messages),
                        "query_preview": query_text[:80],
                        "memory_retrieval_ms": memory_retrieval_ms,
                        "knowledge_setup_ms": knowledge_setup_ms,
                        "knowledge_preflight_ms": knowledge_preflight_ms,
                        "knowledge_retrieval_ms": knowledge_retrieval_ms,
                        "assembly_plan_ms": assembly_plan_ms,
                        "transcript_projection_ms": transcript_projection_ms,
                        "payload_dict_ms": payload_dict_ms,
                        "session_snapshot_write_ms": session_snapshot_write_ms,
                        "tool_count": len(tools),
                        "payload_build_total_ms": round((time.perf_counter() - build_started_at) * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
        return payload

    def normalize_events(self, events: list[OpenAICodexSSEEvent], *, on_partial_text: Callable[[str], None] | None = None) -> ExecutionPlan:
        text_parts: list[str] = []
        final_response_id: str | None = None
        final_status: str | None = None
        final_usage: dict | None = None
        final_model: str | None = None
        pending_tool_name: str | None = None
        pending_tool_arguments: str = ""
        completed_tool_payload: dict | None = None
        for event in events:
            payload = event.payload
            event_type = payload.get("type")

            if final_response_id is None and isinstance(payload.get("response_id"), str):
                final_response_id = payload.get("response_id")
            if final_status is None and isinstance(payload.get("status"), str):
                final_status = payload.get("status")
            if final_model is None and isinstance(payload.get("model"), str):
                final_model = payload.get("model")
            if final_usage is None and isinstance(payload.get("usage"), dict):
                final_usage = payload.get("usage")
            if event_type == "response.output_text.delta":
                delta = payload.get("delta")
                if isinstance(delta, str):
                    text_parts.append(delta)
                    if on_partial_text is not None:
                        try:
                            on_partial_text("".join(text_parts))
                        except Exception:
                            pass
            elif event_type == "response.output_item.added":
                item = payload.get("item") if isinstance(payload.get("item"), dict) else None
                if isinstance(item, dict) and item.get("type") == "function_call":
                    pending_tool_name = item.get("name") if isinstance(item.get("name"), str) else None
                    arguments = item.get("arguments")
                    pending_tool_arguments = arguments if isinstance(arguments, str) else ""
            elif event_type == "response.function_call_arguments.delta":
                delta = payload.get("delta")
                if isinstance(delta, str):
                    pending_tool_arguments += delta
            elif event_type == "response.function_call_arguments.done":
                arguments = payload.get("arguments")
                if isinstance(arguments, str):
                    pending_tool_arguments = arguments
            elif event_type == "response.output_item.done":
                item = payload.get("item") if isinstance(payload.get("item"), dict) else None
                if isinstance(item, dict) and item.get("type") == "function_call":
                    completed_tool_payload = item
                    if isinstance(item.get("name"), str):
                        pending_tool_name = item.get("name")
                    if isinstance(item.get("arguments"), str):
                        pending_tool_arguments = item.get("arguments")
            elif event_type in {"response.completed", "response.done", "response.incomplete"}:
                response = payload.get("response")
                if isinstance(response, dict):
                    if isinstance(response.get("id"), str):
                        final_response_id = response.get("id")
                    if isinstance(response.get("status"), str):
                        final_status = response.get("status")
                    if isinstance(response.get("usage"), dict):
                        final_usage = response.get("usage")
                    if isinstance(response.get("model"), str):
                        final_model = response.get("model")
                    output = response.get("output")
                    if isinstance(output, list):
                        for item in output:
                            if isinstance(item, dict) and item.get("type") == "function_call":
                                completed_tool_payload = item
            elif event_type == "error":
                message = payload.get("message") if isinstance(payload.get("message"), str) else "Codex hosted route returned an error event"
                normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-error-event", failure=ProviderFailure(kind="provider_error", message=message))
                return normalized_result_to_execution_plan(normalized)

        if completed_tool_payload is not None or pending_tool_name is not None:
            tool_name = None
            arguments_text = pending_tool_arguments or "{}"
            if completed_tool_payload is not None and isinstance(completed_tool_payload.get("name"), str):
                tool_name = completed_tool_payload.get("name")
            elif isinstance(pending_tool_name, str):
                tool_name = pending_tool_name
            if tool_name:
                try:
                    input_payload = json.loads(arguments_text)
                except json.JSONDecodeError:
                    input_payload = {"raw_arguments": arguments_text}
                registry = self._effective_capability_tool_registry()
                descriptor = registry.get_tool_descriptor(tool_name)
                try:
                    debug_log(
                        "openai_codex:normalize_events tool_request "
                        + json.dumps(
                            {
                                "event_count": len(events),
                                "response_id": final_response_id,
                                "status": final_status,
                                "model": final_model,
                                "usage": final_usage,
                                "tool_name": tool_name,
                            },
                            ensure_ascii=False,
                        )
                    )
                except Exception:
                    pass
                normalized = ProviderNormalizedResult(
                    source_backend=self.backend_name,
                    plan_label="openai-codex-tool-request",
                    tool_request=ToolRequest(
                        tool_name=tool_name,
                        input_payload=input_payload if isinstance(input_payload, dict) else {"value": input_payload},
                        requires_approval=descriptor.requires_approval,
                        side_effect_class=descriptor.side_effect_class,
                        provider_call_id=(completed_tool_payload.get("call_id") if isinstance(completed_tool_payload, dict) and isinstance(completed_tool_payload.get("call_id"), str) else None),
                    ),
                    should_finish_after_tool=False,
                    metadata={
                        "response_id": final_response_id,
                        "status": final_status,
                        "event_count": len(events),
                        "raw_tool_payload": completed_tool_payload,
                        "usage": final_usage,
                        "model": final_model,
                    },
                )
                return normalized_result_to_execution_plan(normalized)

        final_text = "".join(text_parts).strip()
        if final_text:
            try:
                debug_log(
                    "openai_codex:normalize_events final_text "
                    + json.dumps(
                        {
                            "event_count": len(events),
                            "response_id": final_response_id,
                            "status": final_status,
                            "model": final_model,
                            "usage": final_usage,
                            "text_len": len(final_text),
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception:
                pass
            normalized = ProviderNormalizedResult(
                source_backend=self.backend_name,
                plan_label="openai-codex-final-text",
                final_text=final_text,
                metadata={
                    "response_id": final_response_id,
                    "status": final_status,
                    "event_count": len(events),
                    "usage": final_usage,
                    "model": final_model,
                },
            )
            return normalized_result_to_execution_plan(normalized)
        normalized = ProviderNormalizedResult(
            source_backend=self.backend_name,
            plan_label="openai-codex-malformed-response",
            failure=ProviderFailure(kind="malformed_response", message="Codex hosted response did not yield extractable final text or tool request"),
            metadata={
                "event_count": len(events),
                "response_id": final_response_id,
                "status": final_status,
                "usage": final_usage,
                "model": final_model,
            },
        )
        return normalized_result_to_execution_plan(normalized)
