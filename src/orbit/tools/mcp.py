from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from orbit.runtime.mcp.client import McpClient
from orbit.runtime.mcp.governance import normalize_filesystem_mcp_payload, resolve_mcp_tool_governance
from orbit.runtime.mcp.models import McpToolDescriptor
from orbit.tools.base import Tool, ToolResult


class McpToolWrapper(Tool):
    """Wrap one MCP-discovered tool as an ORBIT Tool.

    First-slice posture:
    - MCP tools enter ORBIT through ORBIT's governed Tool surface
    - unknown MCP tools remain conservative by default
    - known servers/tools may use a first-pass governance overlay
    """

    def __init__(self, descriptor: McpToolDescriptor, client: McpClient):
        self.descriptor = descriptor
        self.client = client
        self.name = descriptor.orbit_tool_name
        self.tool_source = "mcp"
        self.server_name = descriptor.server_name
        self.original_name = descriptor.original_name
        governance = resolve_mcp_tool_governance(
            server_name=descriptor.server_name,
            original_tool_name=descriptor.original_name,
        )
        self.side_effect_class = governance["side_effect_class"]
        self.requires_approval = governance["requires_approval"]
        self.governance_policy_group = governance["governance_policy_group"]
        self.environment_check_kind = governance["environment_check_kind"]
        self.capability_metadata = getattr(getattr(client, "bootstrap", None), "capability_metadata", None)

    def governance_metadata(self) -> dict[str, Any]:
        metadata = super().governance_metadata()
        metadata.update(
            {
                "server_name": self.server_name,
                "original_tool_name": self.original_name,
                "server_args": list(getattr(self.client.bootstrap, "args", []) or []),
                "server_env": dict(getattr(self.client.bootstrap, "env", {}) or {}),
            }
        )
        capability_metadata = self.capability_metadata if isinstance(self.capability_metadata, dict) else None
        if capability_metadata is not None:
            metadata["capability_metadata"] = capability_metadata
        return metadata

    def invoke(self, **kwargs: Any) -> ToolResult:
        normalized_kwargs = normalize_filesystem_mcp_payload(
            original_tool_name=self.descriptor.original_name,
            arguments=kwargs,
            server_args=getattr(self.client.bootstrap, "args", []),
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self.client.call_tool(self.descriptor.original_name, normalized_kwargs)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.client.call_tool, self.descriptor.original_name, normalized_kwargs)
            return future.result()
