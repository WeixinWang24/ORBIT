"""Identity helpers for computing MCP daemon instance keys.

The instance key is a deterministic string that captures the configuration
and code revision of a daemon so the lifecycle layer can decide whether an
already-running daemon is still valid or must be restarted.
"""
from __future__ import annotations

from pathlib import Path

# The future daemon entry-point script.  It may not exist yet during early
# migration phases — callers should tolerate a missing file gracefully.
_FILESYSTEM_SOCKET_SERVER_REL = (
    "src/mcp_servers/system/core/filesystem/socket_server.py"
)

# Resolve repo root the same way bootstrap.py does (4 parents up from this file).
_REPO_ROOT = Path(__file__).resolve().parents[4]


def filesystem_socket_server_code_path() -> Path:
    """Absolute path to the filesystem socket-server entry script."""
    return _REPO_ROOT / _FILESYSTEM_SOCKET_SERVER_REL


def filesystem_socket_server_code_mtime_ns() -> int:
    """Return mtime_ns of the socket-server script, or 0 if it doesn't exist yet."""
    p = filesystem_socket_server_code_path()
    try:
        return p.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def build_filesystem_server_instance_key(
    *,
    workspace_root: str | Path,
    max_read_bytes: int | None = None,
) -> str:
    """Build a deterministic identity key for a filesystem daemon instance.

    The key encodes everything that, if changed, should cause a running daemon
    to be considered stale and restarted:
      - family name (``filesystem``)
      - resolved workspace root
      - max_read_bytes configuration
      - code mtime of the socket-server script

    Format is a simple pipe-delimited string for debuggability.  A future
    phase may switch to a content hash if needed.
    """
    resolved_root = str(Path(workspace_root).resolve())
    mtime = filesystem_socket_server_code_mtime_ns()
    return f"filesystem|{resolved_root}|max_read={max_read_bytes}|mtime_ns={mtime}"


# ---------------------------------------------------------------------------
# Obsidian daemon identity
# ---------------------------------------------------------------------------

_OBSIDIAN_SOCKET_SERVER_REL = (
    "src/mcp_servers/apps/obsidian/socket_server.py"
)


def obsidian_socket_server_code_path() -> Path:
    """Absolute path to the Obsidian socket-server entry script."""
    return _REPO_ROOT / _OBSIDIAN_SOCKET_SERVER_REL


def obsidian_socket_server_code_mtime_ns() -> int:
    """Return mtime_ns of the Obsidian socket-server script, or 0 if it doesn't exist yet."""
    p = obsidian_socket_server_code_path()
    try:
        return p.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def build_obsidian_server_instance_key(
    *,
    vault_root: str | Path,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> str:
    """Build a deterministic identity key for an Obsidian daemon instance.

    The key encodes everything that, if changed, should cause a running daemon
    to be considered stale and restarted:
      - family name (``obsidian``)
      - resolved vault root
      - max_read_chars and max_results configuration
      - code mtime of the socket-server script
    """
    resolved_vault = str(Path(vault_root).resolve())
    mtime = obsidian_socket_server_code_mtime_ns()
    return (
        f"obsidian|{resolved_vault}"
        f"|max_read_chars={max_read_chars}"
        f"|max_results={max_results}"
        f"|mtime_ns={mtime}"
    )
