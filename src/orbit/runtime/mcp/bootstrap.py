from __future__ import annotations

from orbit.runtime.mcp.models import McpClientBootstrap, McpStdioServerConfig
from orbit.runtime.mcp.naming import mcp_tool_prefix, normalize_name_for_mcp


def bootstrap_stdio_mcp_server(config: McpStdioServerConfig) -> McpClientBootstrap:
    return McpClientBootstrap(
        server_name=config.name,
        normalized_name=normalize_name_for_mcp(config.name),
        tool_prefix=mcp_tool_prefix(config.name),
        transport="stdio",
        command=config.command,
        args=list(config.args),
        env=dict(config.env),
    )
