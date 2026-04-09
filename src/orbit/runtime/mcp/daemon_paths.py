"""Workspace-local path helpers for MCP daemon runtime artifacts.

All daemon paths resolve under ``<workspace_root>/.orbit_mcp/``.
This module is intentionally small and side-effect-free, except for
``ensure_orbit_mcp_runtime_dir`` which creates the directory.
"""
from __future__ import annotations

from pathlib import Path

_RUNTIME_DIR_NAME = ".orbit_mcp"


def orbit_mcp_runtime_dir(workspace_root: str | Path) -> Path:
    """Return the MCP daemon runtime directory for *workspace_root*."""
    return Path(workspace_root).resolve() / _RUNTIME_DIR_NAME


def ensure_orbit_mcp_runtime_dir(workspace_root: str | Path) -> Path:
    """Return the MCP daemon runtime directory, creating it if needed."""
    d = orbit_mcp_runtime_dir(workspace_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def filesystem_socket_path(workspace_root: str | Path) -> Path:
    """Unix domain socket path for the filesystem daemon.

    Uses the short name ``fs.sock`` to reduce path length.
    """
    return orbit_mcp_runtime_dir(workspace_root) / "fs.sock"


def filesystem_meta_path(workspace_root: str | Path) -> Path:
    """Metadata sidecar for the filesystem daemon (JSON)."""
    return orbit_mcp_runtime_dir(workspace_root) / "filesystem.meta.json"


def filesystem_log_path(workspace_root: str | Path) -> Path:
    """Log file for the filesystem daemon."""
    return orbit_mcp_runtime_dir(workspace_root) / "filesystem.log"


# ---------------------------------------------------------------------------
# Obsidian daemon paths
# ---------------------------------------------------------------------------


def obsidian_socket_path(workspace_root: str | Path) -> Path:
    """Unix domain socket path for the Obsidian daemon."""
    return orbit_mcp_runtime_dir(workspace_root) / "obsidian.sock"


def obsidian_meta_path(workspace_root: str | Path) -> Path:
    """Metadata sidecar for the Obsidian daemon (JSON)."""
    return orbit_mcp_runtime_dir(workspace_root) / "obsidian.meta.json"


def obsidian_log_path(workspace_root: str | Path) -> Path:
    """Log file for the Obsidian daemon."""
    return orbit_mcp_runtime_dir(workspace_root) / "obsidian.log"
