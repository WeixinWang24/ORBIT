"""Lifecycle helpers for the filesystem MCP daemon.

Phase 2 scope: spawn, detect, and ensure the filesystem daemon process.
The daemon is an independent Python process that binds a Unix domain socket
inside ``<workspace_root>/.orbit_mcp/``.  These helpers manage its lifecycle
without implementing the MCP unix-socket client transport (that is phase 3).
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from orbit.runtime.mcp.bootstrap import ORBIT_CONDA_PYTHON, ORBIT_REPO_ROOT
from orbit.runtime.mcp.daemon_paths import (
    ensure_orbit_mcp_runtime_dir,
    filesystem_log_path,
    filesystem_meta_path,
    filesystem_socket_path,
)
from orbit.runtime.mcp.models import McpClientBootstrap
from orbit.runtime.mcp.server_identity import build_filesystem_server_instance_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON file helpers
# ---------------------------------------------------------------------------


def read_json_file(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file. Return None if the file does not exist."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return json.loads(text)  # let JSONDecodeError propagate


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as pretty JSON, ensuring the parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Daemon meta
# ---------------------------------------------------------------------------


def read_filesystem_daemon_meta(workspace_root: str | Path) -> dict[str, Any] | None:
    """Read the filesystem daemon metadata sidecar."""
    return read_json_file(filesystem_meta_path(workspace_root))


# ---------------------------------------------------------------------------
# Stale artifact cleanup
# ---------------------------------------------------------------------------


def remove_stale_filesystem_daemon_artifacts(workspace_root: str | Path) -> None:
    """Remove stale socket and meta files. Preserves the log file."""
    sock = filesystem_socket_path(workspace_root)
    meta = filesystem_meta_path(workspace_root)
    for p in (sock, meta):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    logger.debug("removed stale daemon artifacts under %s", sock.parent)


# ---------------------------------------------------------------------------
# Socket liveness probe
# ---------------------------------------------------------------------------


def is_unix_socket_connectable(socket_path: Path, *, timeout_seconds: float = 0.5) -> bool:
    """Return True if a real connection to *socket_path* succeeds."""
    if not socket_path.exists():
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        sock.connect(str(socket_path))
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Identity / usability checks
# ---------------------------------------------------------------------------


def filesystem_daemon_expected_instance_key(
    *,
    workspace_root: str | Path,
    max_read_bytes: int | None = None,
) -> str:
    """Thin wrapper — compute the expected instance key for comparison."""
    return build_filesystem_server_instance_key(
        workspace_root=workspace_root,
        max_read_bytes=max_read_bytes,
    )


def filesystem_daemon_is_usable(
    *,
    workspace_root: str | Path,
    max_read_bytes: int | None = None,
) -> bool:
    """Return True only if the daemon is running, connectable, and matches the expected identity."""
    meta = read_filesystem_daemon_meta(workspace_root)
    if meta is None:
        return False

    sock = filesystem_socket_path(workspace_root)
    if not is_unix_socket_connectable(sock):
        return False

    expected_key = filesystem_daemon_expected_instance_key(
        workspace_root=workspace_root,
        max_read_bytes=max_read_bytes,
    )
    return meta.get("server_instance_key") == expected_key


# ---------------------------------------------------------------------------
# Daemon spawning
# ---------------------------------------------------------------------------


def spawn_filesystem_daemon(
    *,
    workspace_root: str | Path,
    max_read_bytes: int | None = None,
) -> int:
    """Start the filesystem daemon as an independent background process.

    Returns the PID of the spawned process.  The daemon writes its own meta
    file and binds the Unix socket; callers should use
    ``wait_for_filesystem_daemon_ready`` to block until it is connectable.
    """
    ws = str(Path(workspace_root).resolve())
    sock = str(filesystem_socket_path(workspace_root))
    instance_key = filesystem_daemon_expected_instance_key(
        workspace_root=workspace_root,
        max_read_bytes=max_read_bytes,
    )
    log_file = filesystem_log_path(workspace_root)

    env = {
        **os.environ,
        "ORBIT_WORKSPACE_ROOT": ws,
        "ORBIT_MCP_SOCKET_PATH": sock,
        "ORBIT_MCP_SERVER_INSTANCE_KEY": instance_key,
        # Ensure the repo root is importable (needed for editable-install layouts).
        "PYTHONPATH": str(ORBIT_REPO_ROOT),
    }
    if max_read_bytes is not None:
        env["ORBIT_MCP_MAX_READ_BYTES"] = str(max_read_bytes)

    ensure_orbit_mcp_runtime_dir(workspace_root)

    log_fh = open(log_file, "a", encoding="utf-8")  # noqa: SIM115 — intentional detached fd
    proc = subprocess.Popen(
        [str(ORBIT_CONDA_PYTHON), "-m", "mcp_servers.system.core.filesystem.socket_server"],
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    log_fh.close()  # child inherits its own copy; avoid fd leak in parent

    # Brief check: if the daemon crashes on startup, surface it early rather
    # than making the caller wait for the full readiness timeout.
    time.sleep(0.1)
    if proc.poll() is not None:
        raise RuntimeError(
            f"filesystem daemon exited immediately (rc={proc.returncode}). "
            f"Check log: {log_file}"
        )

    logger.info(
        "spawned filesystem daemon pid=%d socket=%s instance_key=%s",
        proc.pid, sock, instance_key,
    )
    return proc.pid


# ---------------------------------------------------------------------------
# Readiness wait
# ---------------------------------------------------------------------------


class DaemonReadyTimeout(Exception):
    """Raised when the filesystem daemon does not become ready in time."""


def wait_for_filesystem_daemon_ready(
    *,
    workspace_root: str | Path,
    timeout_seconds: float = 5.0,
) -> None:
    """Block until the daemon meta file exists and the socket is connectable.

    Raises ``DaemonReadyTimeout`` if the deadline expires.
    """
    deadline = time.monotonic() + timeout_seconds
    sock = filesystem_socket_path(workspace_root)
    meta = filesystem_meta_path(workspace_root)
    poll_interval = 0.1

    while time.monotonic() < deadline:
        if meta.exists() and is_unix_socket_connectable(sock):
            logger.debug("filesystem daemon ready at %s", sock)
            return
        time.sleep(poll_interval)

    raise DaemonReadyTimeout(
        f"filesystem daemon did not become ready within {timeout_seconds}s "
        f"(socket={sock}, meta_exists={meta.exists()})"
    )


# ---------------------------------------------------------------------------
# High-level ensure
# ---------------------------------------------------------------------------


def ensure_filesystem_daemon(
    *,
    workspace_root: str | Path,
    max_read_bytes: int | None = None,
) -> None:
    """Ensure the filesystem daemon is running and usable.

    If an existing daemon matches the expected identity and is connectable,
    this is a no-op.  Otherwise stale artifacts are cleaned, a new daemon is
    spawned, and we wait for it to become ready.
    """
    if filesystem_daemon_is_usable(workspace_root=workspace_root, max_read_bytes=max_read_bytes):
        logger.debug("filesystem daemon already usable — skipping spawn")
        return

    logger.info("filesystem daemon not usable — spawning new instance")
    remove_stale_filesystem_daemon_artifacts(workspace_root)
    spawn_filesystem_daemon(workspace_root=workspace_root, max_read_bytes=max_read_bytes)
    wait_for_filesystem_daemon_ready(workspace_root=workspace_root)


def ensure_filesystem_daemon_bootstrap(
    *,
    workspace_root: str,
    max_read_bytes: int | None = None,
) -> McpClientBootstrap:
    """Ensure the daemon is running and return a client bootstrap for it.

    Combines ``ensure_filesystem_daemon`` with
    ``bootstrap_local_filesystem_mcp_daemon`` from bootstrap.py.
    """
    from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_daemon

    ensure_filesystem_daemon(workspace_root=workspace_root, max_read_bytes=max_read_bytes)
    return bootstrap_local_filesystem_mcp_daemon(
        workspace_root=workspace_root,
        max_read_bytes=max_read_bytes,
    )
