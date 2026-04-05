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
from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_server, bootstrap_local_git_mcp_server
from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
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
        self._tool_registry: ToolRegistry | None = None

    def _effective_tool_registry(self) -> ToolRegistry:
        if self._tool_registry is not None:
            return self._tool_registry
        if not self.config.workspace_root:
            raise ValueError("workspace_root is required for tool registry construction")
        registry = ToolRegistry(Path(self.config.workspace_root))
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_filesystem_mcp_server(workspace_root=str(self.config.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_git_mcp_server(workspace_root=str(self.config.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_bash_mcp_server(workspace_root=str(self.config.workspace_root)),
        )
        register_mcp_server_tools(
            registry=registry,
            bootstrap=bootstrap_local_process_mcp_server(workspace_root=str(self.config.workspace_root)),
        )
        self._tool_registry = registry
        return registry

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
        registry = self._effective_tool_registry()
        schema = []
        for tool in registry.list_tools():
            if tool.name == "native__list_available_tools":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return the full callable ORBIT tool inventory from the assembled runtime tool registry, with tool attributes and guidance for selection.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                })
            elif tool.name == "native__describe_tool":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Describe one currently available ORBIT tool from the assembled runtime tool registry.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact tool name to describe."}
                            },
                            "required": ["name"],
                        },
                    },
                })
            elif tool.name == "read_file":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read a file via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}},
                            "required": ["path"],
                        },
                    },
                })
            elif tool.name == "glob":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Match workspace-relative filesystem entries under a base directory using a bounded glob pattern via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Glob pattern relative to the base directory, for example **/*.py or src/*.md."},
                                "path": {"type": "string", "description": "Workspace-relative base directory path. Preferred alias for the glob root. Defaults to the workspace root."},
                                "base_path": {"type": "string", "description": "Workspace-relative base directory path. Legacy-compatible alias for path."},
                                "maxResults": {"type": "integer", "description": "Maximum number of matches to return."},
                                "offset": {"type": "integer", "description": "Skip the first N matches before returning the bounded result page."}
                            },
                            "required": ["pattern"],
                        },
                    },
                })
            elif tool.name == "grep":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Search file contents with ripgrep-style regex semantics inside a workspace-relative path and return bounded structured results via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Regular expression pattern to search for in file contents."},
                                "path": {"type": "string", "description": "Workspace-relative file or directory path. Defaults to the workspace root."},
                                "glob": {"type": "string", "description": "Optional glob filter for candidate files."},
                                "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"], "description": "Result mode."},
                                "-B": {"type": "integer", "description": "Context lines before each match in content mode."},
                                "-A": {"type": "integer", "description": "Context lines after each match in content mode."},
                                "context": {"type": "integer", "description": "Context lines before and after each match in content mode."},
                                "-n": {"type": "boolean", "description": "Show line numbers in content mode."},
                                "-i": {"type": "boolean", "description": "Case-insensitive search."},
                                "type": {"type": "string", "description": "Optional ripgrep file type filter."},
                                "head_limit": {"type": "integer", "description": "Maximum number of lines or entries to return."},
                                "offset": {"type": "integer", "description": "Skip the first N results before returning the bounded page."},
                                "multiline": {"type": "boolean", "description": "Enable multiline regex mode."}
                            },
                            "required": ["pattern"],
                        },
                    },
                })
            elif tool.name == "get_symbols_overview":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return a structured symbol overview for a Python source file using Python AST parsing.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative Python file path."}
                            },
                            "required": ["path"],
                        },
                    },
                })
            elif tool.name == "find_symbol":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Find Python symbol definitions across the workspace or within an optional path scope using Python AST parsing.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact symbol name to search for."},
                                "path": {"type": "string", "description": "Optional workspace-relative file or directory scope."},
                                "kind": {"type": "string", "description": "Optional symbol kind filter, for example class, function, async_function, or method."}
                            },
                            "required": ["name"],
                        },
                    },
                })
            elif tool.name == "find_references":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Find candidate Python identifier references across the workspace or within an optional path scope.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact identifier name to search for."},
                                "path": {"type": "string", "description": "Optional workspace-relative file or directory scope."}
                            },
                            "required": ["name"],
                        },
                    },
                })
            elif tool.name == "read_symbol_body":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read the full body of one Python symbol from a workspace-relative file using AST-derived span boundaries.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative Python file path."},
                                "name": {"type": "string", "description": "Exact symbol name to read."},
                                "kind": {"type": "string", "description": "Optional symbol kind filter, for example class, function, async_function, or method."}
                            },
                            "required": ["path", "name"],
                        },
                    },
                })
            elif tool.name == "run_bash":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Run a bounded shell command in the workspace via the ORBIT MCP bash server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to execute."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum execution time in seconds."}
                            },
                            "required": ["command"],
                        },
                    },
                })
            elif tool.name == "start_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Start a long-running process in the workspace via the ORBIT MCP process server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command to launch."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."}
                            },
                            "required": ["command"],
                        },
                    },
                })
            elif tool.name == "read_process_output":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read incremental stdout/stderr from a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "max_chars": {"type": "integer", "description": "Maximum combined stdout/stderr characters to return."}
                            },
                            "required": ["process_id"],
                        },
                    },
                })
            elif tool.name == "wait_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Wait for a managed ORBIT process to change state or complete.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum wait time in seconds."}
                            },
                            "required": ["process_id"],
                        },
                    },
                })
            elif tool.name == "terminate_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Terminate a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."}
                            },
                            "required": ["process_id"],
                        },
                    },
                })
            elif tool.name == "web_fetch":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Fetch remote web content from an http(s) URL and return bounded extracted text plus basic metadata via the ORBIT MCP filesystem server. This first slice keeps strict SSL verification enabled by default and reports SSL verification failures separately from generic network failures.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "Fully qualified http(s) URL to fetch."},
                                "max_chars": {"type": "integer", "description": "Maximum number of characters to return from the normalized content."},
                                "format_hint": {"type": "string", "description": "Optional hint such as html, markdown, text, or json."},
                                "extract_main_text": {"type": "boolean", "description": "Prefer article/main/body extraction for HTML before text normalization."}
                            },
                            "required": ["url"],
                        },
                    },
                })
            elif tool.name == "git_status":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return structured git working-tree status for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                        },
                    },
                })
            elif tool.name == "git_diff":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return bounded git diff text plus metadata for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git diff."},
                                "staged": {"type": "boolean", "description": "When true, inspect staged changes via git diff --cached."},
                                "max_chars": {"type": "integer", "description": "Optional maximum diff characters to return."}
                            },
                        },
                    },
                })
            elif tool.name == "git_log":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return structured recent commit summaries for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git log."},
                                "limit": {"type": "integer", "description": "Maximum number of commits to return."}
                            },
                        },
                    },
                })
            elif tool.name == "git_show":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Return bounded git show output for a revision, optionally filtered to one path.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "rev": {"type": "string", "description": "Revision specifier, for example HEAD or HEAD~1."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git show."},
                                "max_chars": {"type": "integer", "description": "Optional maximum output characters to return."}
                            },
                            "required": ["rev"],
                        },
                    },
                })
            elif tool.name == "git_add":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Stage one or more paths in the current git repository.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "paths": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}, "minItems": 1}
                                    ],
                                    "description": "One path or a list of paths to stage."
                                },
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["paths"],
                        },
                    },
                })
            elif tool.name == "git_restore":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Restore one or more paths in the working tree from HEAD.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "paths": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}, "minItems": 1}
                                    ],
                                    "description": "One path or a list of paths to restore from HEAD."
                                },
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["paths"],
                        },
                    },
                })
            elif tool.name == "git_commit":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Create a git commit from the current staged changes using an explicit message.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Explicit commit message."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["message"],
                        },
                    },
                })
            elif tool.name == "git_checkout_branch":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Switch to an existing local branch in the current git repository.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "branch": {"type": "string", "description": "Existing branch name to check out."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["branch"],
                        },
                    },
                })
            elif tool.name == "todo_write":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Replace the current session-scoped structured todo list via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "content": {"type": "string"},
                                            "status": {"type": "string"},
                                            "priority": {"type": ["string", "integer", "number", "null"]}
                                        },
                                        "required": ["content"]
                                    }
                                }
                            },
                            "required": ["items"],
                        },
                    },
                })
            elif tool.name == "todo_read":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read the current session-scoped structured todo list via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                })
            elif tool.name == "write_file":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Write UTF-8 text to a workspace-relative file via the ORBIT MCP filesystem server.",
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
            elif tool.name == "run_bash":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Run a bounded shell command in the workspace via the ORBIT MCP bash server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to execute."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum execution time in seconds."}
                            },
                            "required": ["command"],
                        },
                    },
                })
            elif tool.name == "start_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Start a long-running process in the workspace via the ORBIT MCP process server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command to launch."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."}
                            },
                            "required": ["command"],
                        },
                    },
                })
            elif tool.name == "read_process_output":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Read incremental stdout/stderr from a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "max_chars": {"type": "integer", "description": "Maximum combined stdout/stderr characters to return."}
                            },
                            "required": ["process_id"],
                        },
                    },
                })
            elif tool.name == "wait_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Wait for a managed ORBIT process to change state or complete.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum wait time in seconds."}
                            },
                            "required": ["process_id"],
                        },
                    },
                })
            elif tool.name == "terminate_process":
                schema.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": "Terminate a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."}
                            },
                            "required": ["process_id"],
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
        registry = self._effective_tool_registry()
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
