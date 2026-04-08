from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class McpGovernanceMetadata(TypedDict):
    side_effect_class: str
    requires_approval: bool
    governance_policy_group: str
    environment_check_kind: str


DEFAULT_MCP_GOVERNANCE: McpGovernanceMetadata = {
    "side_effect_class": "network",
    "requires_approval": True,
    "governance_policy_group": "permission_authority",
    "environment_check_kind": "none",
}

_BASH_SYSTEM_ENVIRONMENT_TOOLS = {
    "run_bash__read_only",
}

_BASH_PERMISSION_AUTHORITY_TOOLS = {
    "run_bash",
}


_FILESYSTEM_SYSTEM_ENVIRONMENT_TOOLS = {
    "read_file",
    "read_text_file",
    "read_media_file",
    "read_multiple_files",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "search_files",
    "glob",
    "grep",
    "get_file_info",
    "get_symbols_overview",
    "find_symbol",
    "find_references",
    "read_symbol_body",
    "list_allowed_directories",
    "todo_read",
    "todo_write",
    "web_fetch",
}

_FILESYSTEM_PERMISSION_AUTHORITY_TOOLS = {
    "write_file",
    "replace_in_file",
    "replace_all_in_file",
    "replace_block_in_file",
    "apply_exact_hunk",
    "apply_unified_patch",
    "edit_file",
    "create_directory",
    "move_file",
}


_GIT_SYSTEM_ENVIRONMENT_TOOLS = {
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
    "git_changed_files",
}

_GIT_PERMISSION_AUTHORITY_TOOLS = {
    "git_add",
    "git_restore",
    "git_unstage",
    "git_commit",
    "git_checkout_branch",
}

# Structured pytest diagnostics — workspace-scoped, bounded, no-approval for coding workflow.
# Classified as safe/system_environment so a coding agent can run tests without approval gates.
# Note: test execution does run arbitrary code and may write .pytest_cache; this is accepted
# as benign for the first-slice diagnostics use case.
_PYTEST_SYSTEM_ENVIRONMENT_TOOLS = {
    "run_pytest_structured",
}

_RUFF_SYSTEM_ENVIRONMENT_TOOLS = {
    "run_ruff_structured",
}

_MYPY_SYSTEM_ENVIRONMENT_TOOLS = {
    "run_mypy_structured",
}

_BROWSER_SYSTEM_ENVIRONMENT_TOOLS = {
    "browser_open",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_console",
    "browser_screenshot",
}

_OBSIDIAN_SYSTEM_ENVIRONMENT_TOOLS = {
    "obsidian_list_notes",
    "obsidian_read_note",
    "obsidian_search_notes",
    "obsidian_get_note_links",
    "obsidian_get_vault_metadata",
    "obsidian_check_availability",
}


def resolve_mcp_tool_governance(*, server_name: str, original_tool_name: str) -> McpGovernanceMetadata:
    server = server_name.strip().lower()
    tool = original_tool_name.strip().lower()

    if server == "bash":
        if tool in _BASH_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }
        if tool in _BASH_PERMISSION_AUTHORITY_TOOLS:
            return {
                "side_effect_class": "write",
                "requires_approval": True,
                "governance_policy_group": "permission_authority",
                "environment_check_kind": "none",
            }

    if server == "process":
        if tool in {"start_process", "read_process_output", "wait_process", "terminate_process"}:
            return {
                "side_effect_class": "write",
                "requires_approval": True,
                "governance_policy_group": "permission_authority",
                "environment_check_kind": "none",
            }

    if server == "filesystem":
        if tool in _FILESYSTEM_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "path_exists"
                if tool in {
                    "read_file",
                    "read_text_file",
                    "read_media_file",
                    "list_directory",
                    "list_directory_with_sizes",
                    "directory_tree",
                    "search_files",
                    "glob",
                    "grep",
                    "get_file_info",
                }
                else "none",
            }
        if tool in _FILESYSTEM_PERMISSION_AUTHORITY_TOOLS:
            return {
                "side_effect_class": "write",
                "requires_approval": True,
                "governance_policy_group": "permission_authority",
                "environment_check_kind": "none",
            }

    if server == "pytest":
        if tool in _PYTEST_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }

    if server == "ruff":
        if tool in _RUFF_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }

    if server == "mypy":
        if tool in _MYPY_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }

    if server == "browser":
        if tool in _BROWSER_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }

    if server == "git":
        if tool in _GIT_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "path_exists",
            }
        if tool in _GIT_PERMISSION_AUTHORITY_TOOLS:
            return {
                "side_effect_class": "write",
                "requires_approval": True,
                "governance_policy_group": "permission_authority",
                "environment_check_kind": "none",
            }

    if server == "obsidian":
        if tool in _OBSIDIAN_SYSTEM_ENVIRONMENT_TOOLS:
            return {
                "side_effect_class": "safe",
                "requires_approval": False,
                "governance_policy_group": "system_environment",
                "environment_check_kind": "none",
            }

    return dict(DEFAULT_MCP_GOVERNANCE)


def filesystem_server_allowed_root(server_args: list[str], server_env: dict[str, str] | None = None) -> Path | None:
    env = server_env or {}
    env_root = env.get("ORBIT_WORKSPACE_ROOT")
    if isinstance(env_root, str) and env_root.strip():
        try:
            return Path(env_root).resolve()
        except Exception:
            return None
    if not server_args:
        return None
    candidate = server_args[-1]
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    try:
        return Path(candidate).resolve()
    except Exception:
        return None


def normalize_filesystem_mcp_payload(*, original_tool_name: str, arguments: dict[str, Any], server_args: list[str]) -> dict[str, Any]:
    tool = original_tool_name.strip().lower()
    if tool not in _FILESYSTEM_SYSTEM_ENVIRONMENT_TOOLS | _FILESYSTEM_PERMISSION_AUTHORITY_TOOLS:
        return dict(arguments)

    # ORBIT core filesystem MCP server keeps the same workspace-relative
    # canonical path discipline as native tools. Do not rewrite relative
    # paths into absolute ones here.
    return dict(arguments)


def resolve_filesystem_mcp_target_path(*, input_payload: dict[str, Any], server_args: list[str], server_env: dict[str, str] | None = None) -> Path | None:
    allowed_root = filesystem_server_allowed_root(server_args, server_env)
    if allowed_root is None:
        return None
    path_value = input_payload.get("path")
    if not isinstance(path_value, str) or not path_value:
        return None
    path_obj = Path(path_value)
    return path_obj.resolve() if path_obj.is_absolute() else (allowed_root / path_obj).resolve()
