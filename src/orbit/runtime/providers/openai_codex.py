"""OpenAI Codex hosted-provider backend for ORBIT."""

from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential, ResolvedOpenAIAuthMaterial, resolve_openai_auth_material
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore
from orbit.runtime.execution.backends import ExecutionBackend
from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.execution.context_assembly import build_text_only_prompt_assembly_plan
from orbit.knowledge.context_integration import knowledge_bundle_to_context_fragments, knowledge_preflight_to_context_fragments
from orbit.knowledge.models import KnowledgeQuery
from orbit.knowledge.obsidian_service import ObsidianKnowledgeService
from orbit.knowledge.retrieval import retrieve_knowledge_bundle
from orbit.runtime.execution.transcript_projection import messages_to_codex_input
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
        raw = os.environ.get("ORBIT_ENABLE_KNOWLEDGE", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def __init__(self, config: OpenAICodexConfig | None = None, repo_root: Path | None = None, workspace_root: Path | None = None, tool_registry: ToolRegistry | None = None):
        self.config = config or OpenAICodexConfig()
        self.repo_root = repo_root or Path.cwd()
        self.workspace_root = workspace_root or self.repo_root
        self.auth_store = OpenAIAuthStore(self.repo_root)
        self.tool_registry = tool_registry

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
        return registry

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        return self.plan_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def plan_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None, on_partial_text: Callable[[str], None] | None = None) -> ExecutionPlan:
        credential = self.load_persisted_credential()
        auth = self.resolve_auth_material(credential)
        url = self.build_request_url()
        headers = self.build_request_headers(auth)
        payload = self.build_request_payload_from_messages(messages, session=session)
        if session is not None:
            session.metadata["last_provider_payload"] = payload
        try:
            events: list[OpenAICodexSSEEvent] = []
            accumulated_text_parts: list[str] = []
            for event in stream_sse_events(url=url, headers=headers, payload=payload, timeout_seconds=self.config.timeout_seconds):
                events.append(event)
                if on_partial_text is not None:
                    event_type = event.payload.get("type")
                    if event_type == "response.output_text.delta":
                        delta = event.payload.get("delta")
                        if isinstance(delta, str):
                            accumulated_text_parts.append(delta)
                            try:
                                on_partial_text("".join(accumulated_text_parts))
                            except Exception:
                                pass
        except OpenAICodexHttpError as exc:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-transport-failure", failure=ProviderFailure(kind="transport_error", message=str(exc)), metadata={"payload_shape": "codex_messages_projection"})
            return normalized_result_to_execution_plan(normalized)
        # on_partial_text already fired incrementally above; pass None to avoid
        # re-firing the same callbacks during final normalization.
        return self.normalize_events(events, on_partial_text=None)

    def load_persisted_credential(self) -> OpenAIOAuthCredential:
        return self.auth_store.load()

    def resolve_auth_material(self, credential: OpenAIOAuthCredential) -> ResolvedOpenAIAuthMaterial:
        return resolve_openai_auth_material(credential)

    def build_request_headers(self, auth: ResolvedOpenAIAuthMaterial) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.bearer_token}", "Content-Type": "application/json", "Accept": "text/event-stream"}

    def build_request_url(self) -> str:
        return self.config.api_base.rstrip("/") + "/codex/responses"

    def build_request_payload(self, descriptor: RunDescriptor) -> dict:
        return self.build_request_payload_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def build_tool_definitions(self) -> list[dict]:
        registry = self.tool_registry if self.tool_registry is not None else self._effective_tool_registry()
        return [codex_function_definition(tool) for tool in registry.list_tools()]

    def build_request_payload_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> dict:
        latest_user = next((message for message in reversed(messages) if message.role == MessageRole.USER and message.content.strip()), None)
        query_text = latest_user.content if latest_user is not None else messages[-1].content if messages else ""

        memory_fragments = []
        if session is not None and hasattr(self, "memory_service"):
            memory_fragments = self.memory_service.retrieve_memory_fragments(
                session_id=session.session_id,
                query_text=query_text,
                limit=5,
            )

        knowledge_fragments = []
        if session is not None and query_text.strip() and self._knowledge_enabled():
            try:
                vault_root = getattr(getattr(self, "session_manager", None), "_obsidian_vault_root", None)
                resolved_vault_root = vault_root() if callable(vault_root) else "/Volumes/2TB/MAS/vio_vault"
                knowledge_service = ObsidianKnowledgeService(vault_root=resolved_vault_root)

                availability = knowledge_service.check_availability()
                vault_metadata = None
                if availability.get("availability_level") in {"full", "vault_only"}:
                    vault_metadata = knowledge_service.get_vault_metadata(max_entries=5)
                preflight_fragments = knowledge_preflight_to_context_fragments(
                    availability=availability,
                    vault_metadata=vault_metadata,
                )
                knowledge_fragments.extend(preflight_fragments)
                session.metadata["last_knowledge_availability"] = availability
                if vault_metadata is not None:
                    session.metadata["last_knowledge_vault_metadata"] = vault_metadata

                if availability.get("availability_level") in {"full", "vault_only"}:
                    knowledge_bundle = retrieve_knowledge_bundle(
                        query=KnowledgeQuery(query_text=query_text, limit=5),
                        obsidian_service=knowledge_service,
                    )
                    knowledge_fragments.extend(knowledge_bundle_to_context_fragments(knowledge_bundle))
                    session.metadata["last_knowledge_bundle"] = knowledge_bundle.model_dump(mode="json")
            except Exception as exc:
                if session is not None:
                    session.metadata["last_knowledge_error"] = repr(exc)

        auxiliary_fragments = [*memory_fragments, *knowledge_fragments]
        runtime_mode = session.runtime_mode if session is not None else "dev"
        assembly_plan = build_text_only_prompt_assembly_plan(
            backend_name=self.backend_name,
            model=self.config.model,
            messages=messages,
            workspace_root=str(self.workspace_root),
            runtime_mode=runtime_mode,
            auxiliary_fragments=auxiliary_fragments,
        )
        instructions = assembly_plan.effective_instructions
        projected_input = messages_to_codex_input(messages)
        payload = {
            "model": self.config.model,
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": projected_input,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
        }
        tools = []
        if self.config.enable_tools:
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
            tools = self.build_tool_definitions()
            if tools:
                payload["tools"] = tools
        if session is not None:
            snapshot = assembly_plan.to_snapshot_dict()
            snapshot["tooling"] = {
                "enable_tools": self.config.enable_tools,
                "tool_count": len(tools),
            }
            session.metadata["_pending_context_assembly"] = snapshot
            session.metadata["_pending_provider_payload"] = payload.copy()
            payload["prompt_cache_key"] = session.session_id
        return payload

    def normalize_events(self, events: list[OpenAICodexSSEEvent], *, on_partial_text: Callable[[str], None] | None = None) -> ExecutionPlan:
        text_parts: list[str] = []
        final_response_id: str | None = None
        final_status: str | None = None
        pending_tool_name: str | None = None
        pending_tool_arguments: str = ""
        completed_tool_payload: dict | None = None
        for event in events:
            payload = event.payload
            event_type = payload.get("type")
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
                registry = self._effective_tool_registry()
                tool = registry.get(tool_name)
                normalized = ProviderNormalizedResult(
                    source_backend=self.backend_name,
                    plan_label="openai-codex-tool-request",
                    tool_request=ToolRequest(
                        tool_name=tool_name,
                        input_payload=input_payload if isinstance(input_payload, dict) else {"value": input_payload},
                        requires_approval=tool.requires_approval,
                        side_effect_class=tool.side_effect_class,
                    ),
                    should_finish_after_tool=False,
                    metadata={
                        "response_id": final_response_id,
                        "status": final_status,
                        "event_count": len(events),
                        "raw_tool_payload": completed_tool_payload,
                    },
                )
                return normalized_result_to_execution_plan(normalized)

        final_text = "".join(text_parts).strip()
        if final_text:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-final-text", final_text=final_text, metadata={"response_id": final_response_id, "status": final_status, "event_count": len(events)})
            return normalized_result_to_execution_plan(normalized)
        normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-malformed-response", failure=ProviderFailure(kind="malformed_response", message="Codex hosted response did not yield extractable final text or tool request"), metadata={"event_count": len(events), "response_id": final_response_id, "status": final_status})
        return normalized_result_to_execution_plan(normalized)
