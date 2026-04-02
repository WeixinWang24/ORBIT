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


_FILESYSTEM_SYSTEM_ENVIRONMENT_TOOLS = {
    "read_file",
    "read_text_file",
    "read_media_file",
    "read_multiple_files",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
}

_FILESYSTEM_PERMISSION_AUTHORITY_TOOLS = {
    "write_file",
    "edit_file",
    "create_directory",
    "move_file",
}


def resolve_mcp_tool_governance(*, server_name: str, original_tool_name: str) -> McpGovernanceMetadata:
    server = server_name.strip().lower()
    tool = original_tool_name.strip().lower()

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

    return dict(DEFAULT_MCP_GOVERNANCE)


def filesystem_server_allowed_root(server_args: list[str]) -> Path | None:
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

    normalized = dict(arguments)
    allowed_root = filesystem_server_allowed_root(server_args)
    if allowed_root is None:
        return normalized

    path_value = normalized.get("path")
    if isinstance(path_value, str) and path_value:
        path_obj = Path(path_value)
        if not path_obj.is_absolute():
            normalized["path"] = str((allowed_root / path_obj).resolve())

    source_value = normalized.get("source")
    if isinstance(source_value, str) and source_value:
        source_obj = Path(source_value)
        if not source_obj.is_absolute():
            normalized["source"] = str((allowed_root / source_obj).resolve())

    destination_value = normalized.get("destination")
    if isinstance(destination_value, str) and destination_value:
        destination_obj = Path(destination_value)
        if not destination_obj.is_absolute():
            normalized["destination"] = str((allowed_root / destination_obj).resolve())

    paths_value = normalized.get("paths")
    if isinstance(paths_value, list):
        normalized_paths: list[Any] = []
        for item in paths_value:
            if isinstance(item, str) and item:
                item_obj = Path(item)
                normalized_paths.append(str((allowed_root / item_obj).resolve()) if not item_obj.is_absolute() else str(item_obj.resolve()))
            else:
                normalized_paths.append(item)
        normalized["paths"] = normalized_paths

    return normalized


def resolve_filesystem_mcp_target_path(*, input_payload: dict[str, Any], server_args: list[str]) -> Path | None:
    allowed_root = filesystem_server_allowed_root(server_args)
    if allowed_root is None:
        return None
    path_value = input_payload.get("path")
    if not isinstance(path_value, str) or not path_value:
        return None
    path_obj = Path(path_value)
    return path_obj.resolve() if path_obj.is_absolute() else (allowed_root / path_obj).resolve()
