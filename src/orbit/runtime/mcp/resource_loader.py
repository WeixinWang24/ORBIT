from __future__ import annotations

import anyio

from orbit.runtime.mcp.client import build_mcp_client
from orbit.runtime.mcp.models import McpClientBootstrap
from orbit.runtime.mcp.resource_models import McpResourceContent, McpResourceDescriptor


async def async_list_mcp_server_resources(*, bootstrap: McpClientBootstrap) -> list[McpResourceDescriptor]:
    client = build_mcp_client(bootstrap)
    return await client.async_list_resources()


def list_mcp_server_resources(*, bootstrap: McpClientBootstrap) -> list[McpResourceDescriptor]:
    async def _run() -> list[McpResourceDescriptor]:
        return await async_list_mcp_server_resources(bootstrap=bootstrap)

    return anyio.run(_run)


async def async_read_mcp_server_resource(*, bootstrap: McpClientBootstrap, uri: str) -> list[McpResourceContent]:
    client = build_mcp_client(bootstrap)
    return await client.async_read_resource(uri)


def read_mcp_server_resource(*, bootstrap: McpClientBootstrap, uri: str) -> list[McpResourceContent]:
    async def _run() -> list[McpResourceContent]:
        return await async_read_mcp_server_resource(bootstrap=bootstrap, uri=uri)

    return anyio.run(_run)
