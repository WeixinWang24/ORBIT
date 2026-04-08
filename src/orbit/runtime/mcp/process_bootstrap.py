from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server
from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig

# Process: persisted-task continuity. Truth comes from persisted runtime
# artifacts (runner status file, stdout/stderr files, store record), not from
# MCP session state. Contrast with browser (live_host): a fresh server instance
# can fully recover lifecycle truth from persisted files, so transport_importance
# is preferred (efficiency) not required (correctness).
_PROCESS_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="process",
    continuity_type="persisted_task",
    truth_source="persisted_runtime_artifacts",
    layer_role="substrate",
    transport_importance="preferred",
)


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
        # persistent_preferred (not persistent_required): process continuity is grounded
        # in persisted artifacts — runner status file, stdout/stderr files, and the store
        # record — not in MCP session state. A fresh server instance recovers full lifecycle
        # truth from those files. persistent_preferred reuses an existing server process for
        # efficiency, but MCP session continuity is not required for correctness.
        # Contrast with browser, which uses persistent_required because live host state is
        # not recoverable from files; here the runner status file is the primary truth source.
        continuity_mode="persistent_preferred",
        capability_metadata=_PROCESS_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)
