"""Lifecycle helpers for the Obsidian MCP daemon.

Parallels ``daemon_lifecycle.py`` (filesystem) but scoped to Obsidian.
The daemon is an independent Python process that binds a Unix domain socket
inside ``<workspace_root>/.orbit_mcp/``.  These helpers manage its lifecycle.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from orbit.runtime.mcp.bootstrap import ORBIT_CONDA_PYTHON, ORBIT_REPO_ROOT
from orbit.runtime.mcp.daemon_lifecycle import (
    DaemonReadyTimeout,
    is_unix_socket_connectable,
    read_json_file,
)
from orbit.runtime.mcp.daemon_paths import (
    ensure_orbit_mcp_runtime_dir,
    obsidian_log_path,
    obsidian_meta_path,
    obsidian_socket_path,
)
from orbit.runtime.mcp.models import McpClientBootstrap
from orbit.runtime.mcp.server_identity import build_obsidian_server_instance_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daemon meta
# ---------------------------------------------------------------------------


def read_obsidian_daemon_meta(workspace_root: str | Path) -> dict | None:
    """Read the Obsidian daemon metadata sidecar."""
    return read_json_file(obsidian_meta_path(workspace_root))


# ---------------------------------------------------------------------------
# Stale artifact cleanup
# ---------------------------------------------------------------------------


def remove_stale_obsidian_daemon_artifacts(workspace_root: str | Path) -> None:
    """Remove stale socket and meta files. Preserves the log file."""
    sock = obsidian_socket_path(workspace_root)
    meta = obsidian_meta_path(workspace_root)
    for p in (sock, meta):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    logger.debug("removed stale obsidian daemon artifacts under %s", sock.parent)


# ---------------------------------------------------------------------------
# Identity / usability checks
# ---------------------------------------------------------------------------


def obsidian_daemon_expected_instance_key(
    *,
    vault_root: str | Path,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> str:
    """Compute the expected instance key for comparison."""
    return build_obsidian_server_instance_key(
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )


def obsidian_daemon_is_usable(
    *,
    workspace_root: str | Path,
    vault_root: str | Path,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> bool:
    """Return True only if the daemon is running, connectable, and matches the expected identity."""
    meta = read_obsidian_daemon_meta(workspace_root)
    if meta is None:
        return False

    sock = obsidian_socket_path(workspace_root)
    if not is_unix_socket_connectable(sock):
        return False

    expected_key = obsidian_daemon_expected_instance_key(
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )
    return meta.get("server_instance_key") == expected_key


# ---------------------------------------------------------------------------
# Daemon spawning
# ---------------------------------------------------------------------------


def spawn_obsidian_daemon(
    *,
    workspace_root: str | Path,
    vault_root: str | Path,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> int:
    """Start the Obsidian daemon as an independent background process.

    Returns the PID of the spawned process.
    """
    ws = str(Path(workspace_root).resolve())
    vr = str(Path(vault_root).resolve())
    sock = str(obsidian_socket_path(workspace_root))
    instance_key = obsidian_daemon_expected_instance_key(
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )
    log_file = obsidian_log_path(workspace_root)

    env = {
        **os.environ,
        "ORBIT_WORKSPACE_ROOT": ws,
        "ORBIT_OBSIDIAN_VAULT_ROOT": vr,
        "ORBIT_MCP_SOCKET_PATH": sock,
        "ORBIT_MCP_SERVER_INSTANCE_KEY": instance_key,
        "PYTHONPATH": str(ORBIT_REPO_ROOT),
    }
    if max_read_chars is not None:
        env["ORBIT_OBSIDIAN_MAX_READ_CHARS"] = str(max_read_chars)
    if max_results is not None:
        env["ORBIT_OBSIDIAN_MAX_RESULTS"] = str(max_results)

    ensure_orbit_mcp_runtime_dir(workspace_root)

    log_fh = open(log_file, "a", encoding="utf-8")  # noqa: SIM115 — intentional detached fd
    proc = subprocess.Popen(
        [str(ORBIT_CONDA_PYTHON), "-m", "mcp_servers.apps.obsidian.socket_server"],
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    log_fh.close()  # child inherits its own copy; avoid fd leak in parent

    time.sleep(0.1)
    if proc.poll() is not None:
        raise RuntimeError(
            f"obsidian daemon exited immediately (rc={proc.returncode}). "
            f"Check log: {log_file}"
        )

    logger.info(
        "spawned obsidian daemon pid=%d socket=%s instance_key=%s",
        proc.pid, sock, instance_key,
    )
    return proc.pid


# ---------------------------------------------------------------------------
# Readiness wait
# ---------------------------------------------------------------------------


def wait_for_obsidian_daemon_ready(
    *,
    workspace_root: str | Path,
    timeout_seconds: float = 5.0,
) -> None:
    """Block until the daemon meta file exists and the socket is connectable."""
    deadline = time.monotonic() + timeout_seconds
    sock = obsidian_socket_path(workspace_root)
    meta = obsidian_meta_path(workspace_root)
    poll_interval = 0.1

    while time.monotonic() < deadline:
        if meta.exists() and is_unix_socket_connectable(sock):
            logger.debug("obsidian daemon ready at %s", sock)
            return
        time.sleep(poll_interval)

    raise DaemonReadyTimeout(
        f"obsidian daemon did not become ready within {timeout_seconds}s "
        f"(socket={sock}, meta_exists={meta.exists()})"
    )


# ---------------------------------------------------------------------------
# High-level ensure
# ---------------------------------------------------------------------------


def ensure_obsidian_daemon(
    *,
    workspace_root: str | Path,
    vault_root: str | Path,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> None:
    """Ensure the Obsidian daemon is running and usable.

    If an existing daemon matches the expected identity and is connectable,
    this is a no-op.  Otherwise stale artifacts are cleaned, a new daemon is
    spawned, and we wait for it to become ready.
    """
    if obsidian_daemon_is_usable(
        workspace_root=workspace_root,
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    ):
        logger.debug("obsidian daemon already usable -- skipping spawn")
        return

    logger.info("obsidian daemon not usable -- spawning new instance")
    remove_stale_obsidian_daemon_artifacts(workspace_root)
    spawn_obsidian_daemon(
        workspace_root=workspace_root,
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )
    wait_for_obsidian_daemon_ready(workspace_root=workspace_root)


def ensure_obsidian_daemon_bootstrap(
    *,
    workspace_root: str,
    vault_root: str,
    max_read_chars: int | None = None,
    max_results: int | None = None,
) -> McpClientBootstrap:
    """Ensure the daemon is running and return a client bootstrap for it."""
    from orbit.runtime.mcp.bootstrap import bootstrap_local_obsidian_mcp_daemon

    ensure_obsidian_daemon(
        workspace_root=workspace_root,
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )
    return bootstrap_local_obsidian_mcp_daemon(
        workspace_root=workspace_root,
        vault_root=vault_root,
        max_read_chars=max_read_chars,
        max_results=max_results,
    )
