"""OpenAI Codex hosted-provider backend for ORBIT."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from orbit.runtime.execution.transcript_projection import messages_to_codex_input
from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_server, bootstrap_local_git_mcp_server
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.runtime.transports.openai_codex_http import OpenAICodexHttpError, OpenAICodexSSEEvent, stream_sse_events
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
        registry = self._effective_tool_registry()
        definitions: list[dict] = []
        for tool in registry.list_tools():
            if tool.name == "native__list_available_tools":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "List the currently available ORBIT tools from the assembled runtime tool registry, including source and governance metadata.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string", "description": "Optional filter for tool source, for example native or mcp."},
                                "server_name": {"type": "string", "description": "Optional filter for server or capability group name, for example git, filesystem, bash, process, or native."},
                                "side_effect_class": {"type": "string", "description": "Optional filter for governance side-effect class, for example safe or write."},
                                "requires_approval": {"type": "boolean", "description": "Optional filter for tools that do or do not require approval."}
                            },
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "native__describe_tool":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Describe one currently available ORBIT tool from the assembled runtime tool registry.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact tool name to describe."}
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "read_file":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Read a file via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."}
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "list_directory":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "List files and directories inside a workspace-relative directory via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative directory path."}
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "list_directory_with_sizes":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "List files and directories inside a workspace-relative directory with file sizes and summary information via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative directory path."},
                                "sortBy": {"type": "string", "enum": ["name", "size"], "description": "Sort entries by name or size."},
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "get_file_info":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Get structured metadata for a workspace-relative file or directory via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file or directory path."},
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "directory_tree":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Get a bounded recursive directory tree for a workspace-relative directory via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative directory path."},
                                "maxDepth": {"type": "integer", "description": "Maximum directory recursion depth."},
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "glob":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Match workspace-relative filesystem entries under a base directory using a bounded glob pattern via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Glob pattern relative to the base directory, for example **/*.py or src/*.md."},
                                "path": {"type": "string", "description": "Workspace-relative base directory path. Preferred alias for the glob root. Defaults to the workspace root."},
                                "base_path": {"type": "string", "description": "Workspace-relative base directory path. Legacy-compatible alias for path."},
                                "maxResults": {"type": "integer", "description": "Maximum number of matches to return."},
                                "offset": {"type": "integer", "description": "Skip the first N matches before returning the bounded result page."},
                            },
                            "required": ["pattern"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "search_files":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Search UTF-8 text files under a workspace-relative directory and return bounded structured match summaries via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative directory path."},
                                "query": {"type": "string", "description": "Text to search for inside files."},
                                "maxResults": {"type": "integer", "description": "Maximum number of matches to return."},
                                "offset": {"type": "integer", "description": "Skip the first N matches before returning the bounded result page."},
                            },
                            "required": ["path", "query"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "get_symbols_overview":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Return a structured symbol overview for a Python source file using Python AST parsing.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative Python file path."}
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "find_symbol":
                definitions.append(
                    {
                        "type": "function",
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
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "find_references":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Find candidate Python identifier references across the workspace or within an optional path scope.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact identifier name to search for."},
                                "path": {"type": "string", "description": "Optional workspace-relative file or directory scope."}
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "grep":
                definitions.append(
                    {
                        "type": "function",
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
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "web_fetch":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Fetch remote web content from an http(s) URL and return bounded extracted text plus basic metadata via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "Fully qualified http(s) URL to fetch."},
                                "max_chars": {"type": "integer", "description": "Maximum number of characters to return from the normalized content."},
                                "format_hint": {"type": "string", "description": "Optional hint such as html, markdown, text, or json."},
                                "extract_main_text": {"type": "boolean", "description": "Prefer article/main/body extraction for HTML before text normalization."}
                            },
                            "required": ["url"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_status":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Return structured git working-tree status for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                            },
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_diff":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Return bounded git diff text plus metadata for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git diff."},
                                "staged": {"type": "boolean", "description": "When true, inspect staged changes via git diff --cached."},
                                "max_chars": {"type": "integer", "description": "Optional maximum diff characters to return."},
                            },
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_log":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Return structured recent commit summaries for the current workspace or an optional workspace-relative cwd.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git log."},
                                "limit": {"type": "integer", "description": "Maximum number of commits to return."},
                            },
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_show":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Return bounded git show output for a revision, optionally filtered to one path.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "rev": {"type": "string", "description": "Revision specifier, for example HEAD or HEAD~1."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                                "path": {"type": "string", "description": "Optional path filter passed to git show."},
                                "max_chars": {"type": "integer", "description": "Optional maximum output characters to return."},
                            },
                            "required": ["rev"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_add":
                definitions.append(
                    {
                        "type": "function",
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
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_restore":
                definitions.append(
                    {
                        "type": "function",
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
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_commit":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Create a git commit from the current staged changes using an explicit message.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Explicit commit message."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["message"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "git_checkout_branch":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Switch to an existing local branch in the current git repository.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "branch": {"type": "string", "description": "Existing branch name to check out."},
                                "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                            },
                            "required": ["branch"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "todo_write":
                definitions.append(
                    {
                        "type": "function",
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
                                        "required": ["content"],
                                        "additionalProperties": False,
                                    }
                                }
                            },
                            "required": ["items"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "todo_read":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Read the current session-scoped structured todo list via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "write_file":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Write UTF-8 text to a workspace-relative file via the ORBIT MCP filesystem server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."},
                                "content": {"type": "string", "description": "File content to write."},
                            },
                            "required": ["path", "content"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "run_bash":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Run a bounded shell command in the workspace via the ORBIT MCP bash server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to execute."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum execution time in seconds."},
                            },
                            "required": ["command"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "start_process":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Start a long-running process in the workspace via the ORBIT MCP process server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command to launch."},
                                "cwd": {"type": "string", "description": "Workspace-relative working directory."},
                            },
                            "required": ["command"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "read_process_output":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Read incremental stdout/stderr from a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "max_chars": {"type": "integer", "description": "Maximum combined stdout/stderr characters to return."},
                            },
                            "required": ["process_id"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "wait_process":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Wait for a managed ORBIT process to change state or complete.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                                "timeout_seconds": {"type": "integer", "description": "Maximum wait time in seconds."},
                            },
                            "required": ["process_id"],
                            "additionalProperties": False,
                        },
                    }
                )
            elif tool.name == "terminate_process":
                definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": "Terminate a managed ORBIT process.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "process_id": {"type": "string", "description": "Managed process id."},
                            },
                            "required": ["process_id"],
                            "additionalProperties": False,
                        },
                    }
                )
        return definitions

    def build_request_payload_from_messages(self, messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> dict:
        assembly_plan = build_text_only_prompt_assembly_plan(
            backend_name=self.backend_name,
            model=self.config.model,
            messages=messages,
            workspace_root=str(self.workspace_root),
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
