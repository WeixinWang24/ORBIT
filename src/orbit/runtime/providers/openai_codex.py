"""OpenAI Codex hosted-provider backend for ORBIT."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential, ResolvedOpenAIAuthMaterial, resolve_openai_auth_material
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore
from orbit.runtime.execution.backends import ExecutionBackend
from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.execution.transcript_projection import messages_to_codex_input
from orbit.runtime.transports.openai_codex_http import OpenAICodexHttpError, OpenAICodexSSEEvent, post_and_read_sse_events
from orbit.tools.registry import ToolRegistry

OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"


@dataclass
class OpenAICodexConfig:
    model: str = "gpt-5.4"
    api_base: str = OPENAI_CODEX_BASE_URL
    timeout_seconds: int = 60
    enable_tools: bool = True


class OpenAICodexExecutionBackend(ExecutionBackend):
    backend_name = "openai-codex"

    def __init__(self, config: OpenAICodexConfig | None = None, repo_root: Path | None = None):
        self.config = config or OpenAICodexConfig()
        self.repo_root = repo_root or Path.cwd()
        self.auth_store = OpenAIAuthStore(self.repo_root)

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        return self.plan_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def plan_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> ExecutionPlan:
        credential = self.load_persisted_credential()
        auth = self.resolve_auth_material(credential)
        url = self.build_request_url()
        headers = self.build_request_headers(auth)
        payload = self.build_request_payload_from_messages(messages, session=session)
        try:
            events = post_and_read_sse_events(url=url, headers=headers, payload=payload, timeout_seconds=self.config.timeout_seconds)
        except OpenAICodexHttpError as exc:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="openai-codex-transport-failure", failure=ProviderFailure(kind="transport_error", message=str(exc)), metadata={"payload_shape": "codex_messages_projection"})
            return normalized_result_to_execution_plan(normalized)
        return self.normalize_events(events)

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
        registry = ToolRegistry(self.repo_root)
        definitions: list[dict] = []
        for tool in registry.list_tools():
            if tool.name == "read_file":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Read a file from the ORBIT workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."}
                            },
                            "required": ["path"],
                        },
                    }
                )
            elif tool.name == "write_file":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Write text content to a file in the ORBIT workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."},
                                "content": {"type": "string", "description": "File content to write."},
                            },
                            "required": ["path", "content"],
                        },
                    }
                )
        return definitions

    def build_request_payload_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> dict:
        payload = {
            "model": self.config.model,
            "store": False,
            "stream": True,
            "instructions": "You are ORBIT's hosted-provider Codex path. Continue the conversation naturally using the supplied transcript.",
            "input": messages_to_codex_input(messages),
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
        }
        if self.config.enable_tools:
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
            tools = self.build_tool_definitions()
            if tools:
                payload["tools"] = tools
        if session is not None:
            payload["prompt_cache_key"] = session.session_id
        return payload

    def normalize_events(self, events: list[OpenAICodexSSEEvent]) -> ExecutionPlan:
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
                registry = ToolRegistry(self.repo_root)
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
