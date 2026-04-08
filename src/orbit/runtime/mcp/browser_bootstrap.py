from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server
from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig

# Browser: live host continuity. Correctness depends on the live MCP server
# process because all browser state lives in the host session. MCP session
# continuity is required — a restart loses the live browsing context entirely.
_BROWSER_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="browser",
    continuity_type="live_host",
    truth_source="live_host_state",
    layer_role="substrate",
    transport_importance="required",
)


def bootstrap_local_browser_mcp_server(*, workspace_root: str) -> McpClientBootstrap:
    repo_root = Path(__file__).resolve().parents[3]
    server_path = repo_root / "mcp_servers" / "system" / "core" / "browser" / "stdio_server.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    env["ORBIT_WORKSPACE_ROOT"] = workspace_root
    config = McpStdioServerConfig(
        name="browser",
        command=sys.executable,
        args=[str(server_path)],
        env=env,
        continuity_mode="persistent_required",
        capability_metadata=_BROWSER_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)
