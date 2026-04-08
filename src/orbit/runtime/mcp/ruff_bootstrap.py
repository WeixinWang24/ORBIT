from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server
from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig

# Diagnostics family: bounded result. See pytest_bootstrap.py for rationale.
_RUFF_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="diagnostics",
    continuity_type="bounded_result",
    truth_source="bounded_result_object",
    layer_role="interpretation",
    transport_importance="irrelevant",
)


def bootstrap_local_ruff_mcp_server(*, workspace_root: str) -> McpClientBootstrap:
    repo_root = Path(__file__).resolve().parents[3]
    server_path = repo_root / "mcp_servers" / "system" / "core" / "ruff" / "stdio_server.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    env["ORBIT_WORKSPACE_ROOT"] = workspace_root
    config = McpStdioServerConfig(
        name="ruff",
        command=sys.executable,
        args=[str(server_path)],
        env=env,
        continuity_mode="stateless",
        capability_metadata=_RUFF_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)
