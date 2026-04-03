from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from orbit.runtime.mcp.models import McpClientBootstrap, McpToolDescriptor
from orbit.runtime.mcp.resource_models import McpResourceContent, McpResourceDescriptor
from orbit.tools.base import ToolResult

DEFAULT_MCP_TIMEOUT_SECONDS = 15


class McpClient(Protocol):
    def list_tools(self) -> list[McpToolDescriptor]:
        raise NotImplementedError

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def list_resources(self) -> list[McpResourceDescriptor]:
        raise NotImplementedError

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        raise NotImplementedError


@dataclass
class StdioMcpClient:
    """Primary stdio MCP client implementation for ORBIT's first MCP slice.

    Current posture:
    - ORBIT keeps its own bootstrap / naming / wrapper / registry architecture
    - stdio transport and protocol handling should prefer the official Python `mcp` SDK
    - the local `stdio_transport.py` shim remains only as a legacy/debug baseline,
      not as the primary client path
    """

    bootstrap: McpClientBootstrap

    async def async_list_tools(self) -> list[McpToolDescriptor]:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    descriptors: list[McpToolDescriptor] = []
                    for item in result.tools:
                        original_name = getattr(item, "name", None)
                        if not isinstance(original_name, str) or not original_name:
                            continue
                        description = getattr(item, "description", None)
                        input_schema = getattr(item, "inputSchema", None)
                        descriptors.append(
                            McpToolDescriptor(
                                server_name=self.bootstrap.server_name,
                                original_name=original_name,
                                orbit_tool_name=self.orbit_tool_name(original_name),
                                description=description if isinstance(description, str) else None,
                                input_schema=input_schema if isinstance(input_schema, dict) else None,
                            )
                        )
                    return descriptors

    def list_tools(self) -> list[McpToolDescriptor]:
        return anyio.run(self.async_list_tools)

    async def async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    content = getattr(result, "content", [])
                    text_parts: list[str] = []
                    if isinstance(content, list):
                        for item in content:
                            item_type = getattr(item, "type", None)
                            item_text = getattr(item, "text", None)
                            if item_type == "text" and isinstance(item_text, str):
                                text_parts.append(item_text)
                    output_text = "\n".join(text_parts).strip()
                    is_error = bool(getattr(result, "isError", False))
                    raw_result = result.model_dump(mode="json") if hasattr(result, "model_dump") else {"content": output_text, "isError": is_error}
                    return ToolResult(
                        ok=not is_error,
                        content=output_text,
                        data={"raw_result": raw_result},
                    )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return anyio.run(self.async_call_tool, tool_name, arguments)

    async def async_list_resources(self) -> list[McpResourceDescriptor]:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_resources()
                    descriptors: list[McpResourceDescriptor] = []
                    for item in getattr(result, "resources", []) or []:
                        uri = getattr(item, "uri", None)
                        name = getattr(item, "name", None)
                        if not isinstance(uri, str) or not uri or not isinstance(name, str) or not name:
                            continue
                        descriptors.append(
                            McpResourceDescriptor(
                                server_name=self.bootstrap.server_name,
                                resource_uri=uri,
                                resource_name=name,
                                description=getattr(item, "description", None) if isinstance(getattr(item, "description", None), str) else None,
                                mime_type=getattr(item, "mimeType", None) if isinstance(getattr(item, "mimeType", None), str) else None,
                            )
                        )
                    return descriptors

    def list_resources(self) -> list[McpResourceDescriptor]:
        return anyio.run(self.async_list_resources)

    async def async_read_resource(self, uri: str) -> list[McpResourceContent]:
        parsed = urlparse(uri)
        if not isinstance(uri, str) or not uri.strip() or not parsed.scheme:
            raise ValueError(f"invalid MCP resource URI: {uri!r}")
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.read_resource(uri)
                    contents: list[McpResourceContent] = []
                    for item in getattr(result, "contents", []) or []:
                        raw_item = item.model_dump(mode="json") if hasattr(item, "model_dump") else None
                        contents.append(
                            McpResourceContent(
                                uri=getattr(item, "uri", uri),
                                mime_type=getattr(item, "mimeType", None) if isinstance(getattr(item, "mimeType", None), str) else None,
                                text=getattr(item, "text", None) if isinstance(getattr(item, "text", None), str) else None,
                                blob=getattr(item, "blob", None) if isinstance(getattr(item, "blob", None), str) else None,
                                raw_item=raw_item,
                            )
                        )
                    return contents

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        return anyio.run(self.async_read_resource, uri)

    def orbit_tool_name(self, original_tool_name: str) -> str:
        return original_tool_name


def build_mcp_client(bootstrap: McpClientBootstrap) -> McpClient:
    if bootstrap.transport == "stdio":
        return StdioMcpClient(bootstrap=bootstrap)
    raise ValueError(f"unsupported MCP transport: {bootstrap.transport}")
