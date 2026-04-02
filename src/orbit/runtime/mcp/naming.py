from __future__ import annotations


def normalize_name_for_mcp(name: str) -> str:
    normalized = []
    for ch in name:
        if ch.isalnum() or ch in {"_", "-"}:
            normalized.append(ch)
        else:
            normalized.append("_")
    return "".join(normalized)


def mcp_tool_prefix(server_name: str) -> str:
    return f"mcp__{normalize_name_for_mcp(server_name)}__"


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"{mcp_tool_prefix(server_name)}{normalize_name_for_mcp(tool_name)}"
