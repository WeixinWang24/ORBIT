"""SSH vLLM backend scaffold for ORBIT provider-comparison work."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.execution.backends import ExecutionBackend
from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.execution.transcript_projection import messages_to_chat_completions_messages
from orbit.runtime.transports.ssh_tunnel import SshTunnelConfig
from orbit.runtime.transports.ssh_vllm_http import SshVllmHttpError, ensure_ssh_vllm_endpoint, post_ssh_vllm_json
from orbit.tools.registry import ToolRegistry


@dataclass
class SshVllmConfig:
    ssh_host: str = ""
    remote_base_url: str = "http://127.0.0.1:8000/v1"
    model: str = "default"
    timeout_seconds: int = 60
    api_key: str = "EMPTY"
    auto_tunnel: bool = False
    local_port: int = 8000
    remote_host: str = "127.0.0.1"
    remote_port: int = 8000
    workspace_root: str | None = None


class SshVllmExecutionBackend(ExecutionBackend):
    backend_name = "ssh-vllm"

    def __init__(self, config: SshVllmConfig | None = None):
        self.config = config or SshVllmConfig()

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        return self.plan_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)], session=None)

    def plan_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> ExecutionPlan:
        return self._plan_with_base_url_from_messages(messages, self.config.remote_base_url)

    def _plan_with_base_url_from_messages(self, messages: list[ConversationMessage], base_url: str) -> ExecutionPlan:
        headers = self.build_request_headers()
        tunnel_config = None
        if self.config.auto_tunnel:
            tunnel_config = SshTunnelConfig(ssh_host=self.config.ssh_host, local_port=self.config.local_port, remote_host=self.config.remote_host, remote_port=self.config.remote_port)
        try:
            ready_base_url = ensure_ssh_vllm_endpoint(base_url=base_url, headers=headers, auto_tunnel=self.config.auto_tunnel, tunnel_config=tunnel_config)
            url = self.build_request_url(ready_base_url)
            payload = self.build_request_payload_from_messages(messages)
            response = post_ssh_vllm_json(url=url, headers=headers, payload=payload, timeout_seconds=self.config.timeout_seconds)
        except SshVllmHttpError as exc:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="ssh-vllm-transport-failure", failure=ProviderFailure(kind="transport_error", message=str(exc)), metadata={"base_url": base_url})
            return normalized_result_to_execution_plan(normalized)
        return self.normalize_response(response.json_body)

    def build_request_url(self, base_url: str | None = None) -> str:
        resolved = (base_url or self.config.remote_base_url).rstrip("/")
        return resolved + "/chat/completions"

    def build_request_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}

    def build_request_payload(self, descriptor: RunDescriptor) -> dict:
        return self.build_request_payload_from_messages([ConversationMessage(session_id=descriptor.session_key, role=MessageRole.USER, content=descriptor.user_input, turn_index=1)])

    def build_tool_schema(self) -> list[dict]:
        if not self.config.workspace_root:
            return []
        registry = ToolRegistry(Path(self.config.workspace_root))
        schema = []
        for tool in registry.list_tools():
            if tool.name == "native__read_file":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read a file from the ORBIT workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}},
                            "required": ["path"],
                        },
                    },
                })
            elif tool.name == "native__write_file":
                schema.append({
                    "type": "function",
                    "function": {
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
                    },
                })
        return schema

    def build_request_payload_from_messages(self, messages: list[ConversationMessage]) -> dict:
        payload = {"model": self.config.model, "messages": messages_to_chat_completions_messages(messages), "stream": False}
        tools = self.build_tool_schema()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def extract_raw_tool_call(self, payload: dict) -> dict | None:
        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else None
        message = first_choice.get("message") if isinstance(first_choice, dict) and isinstance(first_choice.get("message"), dict) else None
        tool_calls = message.get("tool_calls") if isinstance(message, dict) and isinstance(message.get("tool_calls"), list) else []
        first_tool_call = tool_calls[0] if tool_calls and isinstance(tool_calls[0], dict) else None
        return first_tool_call

    def extract_tool_request(self, payload: dict) -> ToolRequest | None:
        raw = self.extract_raw_tool_call(payload)
        if raw is None:
            return None
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        tool_name = function.get("name") if isinstance(function.get("name"), str) else None
        arguments_text = function.get("arguments") if isinstance(function.get("arguments"), str) else "{}"
        if not tool_name:
            return None
        try:
            input_payload = json.loads(arguments_text)
        except json.JSONDecodeError:
            input_payload = {"raw_arguments": arguments_text}
        if not self.config.workspace_root:
            return ToolRequest(tool_name=tool_name, input_payload=input_payload)
        registry = ToolRegistry(Path(self.config.workspace_root))
        tool = registry.get(tool_name)
        return ToolRequest(
            tool_name=tool_name,
            input_payload=input_payload if isinstance(input_payload, dict) else {"value": input_payload},
            requires_approval=tool.requires_approval,
            side_effect_class=tool.side_effect_class,
        )

    def normalize_response(self, payload: dict) -> ExecutionPlan:
        raw_tool_call = self.extract_raw_tool_call(payload)
        tool_request = self.extract_tool_request(payload)
        if tool_request is not None:
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="ssh-vllm-tool-request", tool_request=tool_request, should_finish_after_tool=False, metadata={"raw_tool_call": raw_tool_call, "model": payload.get("model")})
            return normalized_result_to_execution_plan(normalized)
        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else None
        message = first_choice.get("message") if isinstance(first_choice, dict) and isinstance(first_choice.get("message"), dict) else None
        content = message.get("content") if isinstance(message, dict) and isinstance(message.get("content"), str) else None
        finish_reason = first_choice.get("finish_reason") if isinstance(first_choice, dict) and isinstance(first_choice.get("finish_reason"), str) else None
        if content and content.strip():
            normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="ssh-vllm-final-text", final_text=content.strip(), metadata={"id": payload.get("id"), "model": payload.get("model"), "finish_reason": finish_reason, "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {}, "raw_tool_call": raw_tool_call})
            return normalized_result_to_execution_plan(normalized)
        normalized = ProviderNormalizedResult(source_backend=self.backend_name, plan_label="ssh-vllm-malformed-response", failure=ProviderFailure(kind="malformed_response", message="SSH vLLM response did not contain extractable final text or tool request"), metadata={"raw_tool_call": raw_tool_call})
        return normalized_result_to_execution_plan(normalized)
