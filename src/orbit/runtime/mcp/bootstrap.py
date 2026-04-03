from __future__ import annotations

from pathlib import Path

from orbit.runtime.mcp.models import McpClientBootstrap, McpStdioServerConfig
from orbit.runtime.mcp.naming import normalize_name_for_mcp

ORBIT_CONDA_PYTHON = Path("/Users/visen24/anaconda3/envs/Orbit/bin/python")


def bootstrap_stdio_mcp_server(config: McpStdioServerConfig) -> McpClientBootstrap:
    return McpClientBootstrap(
        server_name=config.name,
        normalized_name=normalize_name_for_mcp(config.name),
        tool_prefix="",
        transport="stdio",
        command=config.command,
        args=list(config.args),
        env=dict(config.env),
    )


def bootstrap_local_filesystem_mcp_server(*, workspace_root: str, max_read_bytes: int | None = None) -> McpClientBootstrap:
    env = {"ORBIT_WORKSPACE_ROOT": workspace_root}
    if max_read_bytes is not None:
        env["ORBIT_MCP_MAX_READ_BYTES"] = str(max_read_bytes)
    config = McpStdioServerConfig(
        name="filesystem",
        command=str(ORBIT_CONDA_PYTHON),
        args=["-m", "mcp_servers.system.core.filesystem.stdio_server"],
        env=env,
    )
    return bootstrap_stdio_mcp_server(config)
