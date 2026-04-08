from __future__ import annotations

import os
import sys
from pathlib import Path

from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig
from orbit.runtime.mcp.naming import normalize_name_for_mcp

# Resolve the Orbit conda-environment Python executable.
# Prefer ORBIT_CONDA_PYTHON env-var override (useful in CI or non-standard layouts),
# then fall back to the running interpreter so editable-install workflows just work.
_conda_python_override = os.environ.get("ORBIT_CONDA_PYTHON", "").strip()
ORBIT_CONDA_PYTHON = Path(_conda_python_override) if _conda_python_override else Path(sys.executable)
ORBIT_REPO_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Capability metadata declarations for filesystem and git families.
# Defined here because both are bootstrapped from this module.
# ---------------------------------------------------------------------------

_FILESYSTEM_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="filesystem",
    # stateless: the server process is ephemeral; each call spawns a fresh instance.
    # The workspace root is injected via env var at startup time (configuration, not
    # live session state). Truth comes from the underlying filesystem, not from any
    # session record maintained by the server. transport_importance is irrelevant.
    continuity_type="stateless",
    truth_source="filesystem_or_repo_truth",
    layer_role="substrate",
    transport_importance="irrelevant",
)

_GIT_CAPABILITY_METADATA = McpCapabilityMetadata(
    capability_family="git",
    continuity_type="stateless",
    truth_source="filesystem_or_repo_truth",
    layer_role="access_support",
    transport_importance="irrelevant",
)


def bootstrap_stdio_mcp_server(config: McpStdioServerConfig) -> McpClientBootstrap:
    return McpClientBootstrap(
        server_name=config.name,
        normalized_name=normalize_name_for_mcp(config.name),
        tool_prefix="",
        transport="stdio",
        command=config.command,
        args=list(config.args),
        env=dict(config.env),
        continuity_mode=config.continuity_mode,
        capability_metadata=config.capability_metadata,
    )


def bootstrap_local_filesystem_mcp_server(*, workspace_root: str, max_read_bytes: int | None = None, session_id: str | None = None) -> McpClientBootstrap:
    env = {"ORBIT_WORKSPACE_ROOT": workspace_root}
    if max_read_bytes is not None:
        env["ORBIT_MCP_MAX_READ_BYTES"] = str(max_read_bytes)
    if session_id is not None:
        env["ORBIT_SESSION_ID"] = str(session_id)
    config = McpStdioServerConfig(
        name="filesystem",
        command=str(ORBIT_CONDA_PYTHON),
        args=["-m", "mcp_servers.system.core.filesystem.stdio_server"],
        env=env,
        continuity_mode="stateless",
        capability_metadata=_FILESYSTEM_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)


def bootstrap_local_git_mcp_server(*, workspace_root: str) -> McpClientBootstrap:
    env = {"ORBIT_WORKSPACE_ROOT": workspace_root}
    config = McpStdioServerConfig(
        name="git",
        command=str(ORBIT_CONDA_PYTHON),
        args=["-m", "mcp_servers.system.core.git.stdio_server"],
        env=env,
        continuity_mode="stateless",
        capability_metadata=_GIT_CAPABILITY_METADATA,
    )
    return bootstrap_stdio_mcp_server(config)


def bootstrap_local_obsidian_mcp_server(*, vault_root: str, max_read_chars: int | None = None, max_results: int | None = None) -> McpClientBootstrap:
    env = {
        "ORBIT_OBSIDIAN_VAULT_ROOT": vault_root,
        "PYTHONPATH": str(ORBIT_REPO_ROOT),
    }
    if max_read_chars is not None:
        env["ORBIT_OBSIDIAN_MAX_READ_CHARS"] = str(max_read_chars)
    if max_results is not None:
        env["ORBIT_OBSIDIAN_MAX_RESULTS"] = str(max_results)
    config = McpStdioServerConfig(
        name="obsidian",
        command=str(ORBIT_CONDA_PYTHON),
        args=["-m", "src.mcp_servers.apps.obsidian.stdio_server"],
        env=env,
        continuity_mode="stateless",
        # TODO(capability-metadata): capability_metadata intentionally omitted for the
        # first slice. Obsidian is not in McpCapabilityFamily yet; it would need a family
        # classification (e.g., "knowledge_base") and posture declaration before metadata
        # can be added here. Leaving None is explicit and searchable.
    )
    return bootstrap_stdio_mcp_server(config)
