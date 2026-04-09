from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server
from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig

# Bash: stateless access support. Each invocation is independent; truth comes
# from the bounded result object. The MCP server process lifecycle is irrelevant.
_BASH_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="bash",
    continuity_type="stateless",
    truth_source="bounded_result_object",
    layer_role="access_support",
    transport_importance="irrelevant",
)


def bootstrap_local_bash_mcp_server(*, workspace_root: str) -> McpClientBootstrap:
    repo_root = Path(__file__).resolve().parents[3]
    server_path = repo_root / "mcp_servers" / "system" / "core" / "bash" / "stdio_server.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["ORBIT_WORKSPACE_ROOT"] = workspace_root
    config = McpStdioServerConfig(
        name="bash",
        command=sys.executable,
        args=[str(server_path)],
        env=env,
        continuity_mode="persistent_preferred",
        capability_metadata=_BASH_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)
