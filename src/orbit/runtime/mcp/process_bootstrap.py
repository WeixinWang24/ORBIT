from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server
from orbit.runtime.mcp.models import McpClientBootstrap, McpStdioServerConfig


def bootstrap_local_process_mcp_server(*, workspace_root: str) -> McpClientBootstrap:
    repo_root = Path(__file__).resolve().parents[3]
    server_path = repo_root / "mcp_servers" / "system" / "core" / "process" / "stdio_server.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["ORBIT_WORKSPACE_ROOT"] = workspace_root
    env["ORBIT_PROCESS_DB_PATH"] = str(Path(workspace_root).resolve() / ".orbit_process" / "process-runtime.db")
    config = McpStdioServerConfig(
        name="process",
        command=sys.executable,
        args=[str(server_path)],
        env=env,
    )
    return bootstrap_stdio_mcp_server(config)
