from __future__ import annotations

import anyio

from orbit.runtime.mcp.client import build_mcp_client
from orbit.runtime.mcp.models import McpClientBootstrap
from orbit.runtime.mcp.persistent_client_registry import PERSISTENT_MCP_CLIENT_REGISTRY
from orbit.tools.mcp import McpToolWrapper
from orbit.tools.registry import ToolRegistry


def _build_runtime_mcp_client(bootstrap: McpClientBootstrap):
    """Select the MCP client according to declared capability continuity posture."""
    if bootstrap.transport == "unix_socket":
        # Daemon socket clients are inherently persistent (the daemon stays
        # alive); no need to route through the persistent stdio registry.
        return build_mcp_client(bootstrap)
    mode = getattr(bootstrap, "continuity_mode", "stateless")
    if mode in {"persistent_preferred", "persistent_required"}:
        return PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create(bootstrap)
    return build_mcp_client(bootstrap)


async def async_register_mcp_server_tools(*, registry: ToolRegistry, bootstrap: McpClientBootstrap) -> list[str]:
    """Build one MCP client, wrap its discovered tools, and register them.

    Async-friendly version for notebook/event-loop contexts.
    """
    client = _build_runtime_mcp_client(bootstrap)
    descriptors = await client.async_list_tools()
    wrapped = [McpToolWrapper(descriptor=descriptor, client=client) for descriptor in descriptors]
    registry.register_many(wrapped)
    return [tool.name for tool in wrapped]


def register_mcp_server_tools(*, registry: ToolRegistry, bootstrap: McpClientBootstrap) -> list[str]:
    """Build one MCP client, wrap its discovered tools, and register them.

    First-slice scope:
    - build the client from normalized bootstrap
    - discover tool descriptors via the client
    - wrap descriptors as ORBIT tools
    - register wrapped tools in ToolRegistry
    - return registered tool names for inspection/debugging
    """
    async def _run() -> list[str]:
        return await async_register_mcp_server_tools(registry=registry, bootstrap=bootstrap)

    return anyio.run(_run)
