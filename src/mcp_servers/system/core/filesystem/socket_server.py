"""Filesystem MCP daemon — independent long-lived socket server process.

Phase 3 daemon transport
------------------------
This script runs as a standalone process, independently of the ORBIT CLI.
It binds a Unix domain socket inside the workspace runtime directory and
serves real ``list_tools`` / ``call_tool`` requests over a simple
newline-delimited JSON protocol.

**This is an ORBIT-local daemon bridge protocol, not standard MCP.**
See ``orbit.runtime.mcp.socket_protocol`` for the wire format spec.
The protocol is request-per-connection: the client connects, sends one
JSON-line request, and receives one JSON-line response, then the connection
is closed.

The actual filesystem tool implementations are imported from the existing
``stdio_server`` module so there is a single source of truth.

Configuration is read entirely from environment variables set by the
lifecycle spawner.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import signal
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Env-var config
# ---------------------------------------------------------------------------

_REQUIRED_ENV = {
    "ORBIT_WORKSPACE_ROOT",
    "ORBIT_MCP_SOCKET_PATH",
    "ORBIT_MCP_SERVER_INSTANCE_KEY",
}


def load_server_config_from_env() -> dict[str, Any]:
    """Read and validate daemon configuration from environment variables."""
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(sorted(missing))}")

    config: dict[str, Any] = {
        "workspace_root": os.environ["ORBIT_WORKSPACE_ROOT"].strip(),
        "socket_path": os.environ["ORBIT_MCP_SOCKET_PATH"].strip(),
        "server_instance_key": os.environ["ORBIT_MCP_SERVER_INSTANCE_KEY"].strip(),
        "max_read_bytes": None,
    }

    raw_max = os.environ.get("ORBIT_MCP_MAX_READ_BYTES", "").strip()
    if raw_max:
        config["max_read_bytes"] = int(raw_max)

    return config


# ---------------------------------------------------------------------------
# Meta payload
# ---------------------------------------------------------------------------


def filesystem_daemon_meta_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the metadata sidecar payload for the running daemon."""
    return {
        "server_name": "filesystem",
        "socket_path": config["socket_path"],
        "server_instance_key": config["server_instance_key"],
        "pid": os.getpid(),
        "workspace_root": config["workspace_root"],
        "max_read_bytes": config["max_read_bytes"],
        "started_at": time.time(),
    }


def write_filesystem_daemon_meta(config: dict[str, Any]) -> None:
    """Write the daemon metadata sidecar JSON file."""
    ws = config["workspace_root"]
    from orbit.runtime.mcp.daemon_paths import filesystem_meta_path

    meta_path = filesystem_meta_path(ws)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = filesystem_daemon_meta_payload(config)
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Stale socket cleanup
# ---------------------------------------------------------------------------


def remove_existing_socket_if_stale(socket_path: Path) -> None:
    """Remove a pre-existing socket file so we can bind a fresh one."""
    try:
        if socket_path.exists():
            socket_path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Runtime cleanup
# ---------------------------------------------------------------------------


def cleanup_filesystem_daemon_runtime(config: dict[str, Any]) -> None:
    """Best-effort removal of socket and meta on shutdown."""
    for key in ("socket_path",):
        p = Path(config.get(key, ""))
        try:
            p.unlink()
        except (FileNotFoundError, OSError):
            pass

    try:
        from orbit.runtime.mcp.daemon_paths import filesystem_meta_path
        filesystem_meta_path(config["workspace_root"]).unlink()
    except (FileNotFoundError, OSError):
        pass


# ---------------------------------------------------------------------------
# Request dispatch — reuses real filesystem tool implementations
# ---------------------------------------------------------------------------


def _build_tool_list() -> list[dict[str, Any]]:
    """Return the filesystem tool descriptors as plain dicts.

    Imports the ``list_tools`` coroutine from stdio_server and runs it to get
    the canonical tool list, then serializes each ``types.Tool`` to a dict.
    """
    from mcp_servers.system.core.filesystem.stdio_server import list_tools as _list_tools_coro
    tools = asyncio.run(_list_tools_coro())
    result: list[dict[str, Any]] = []
    for t in tools:
        result.append({
            "name": t.name,
            "description": getattr(t, "description", None),
            "inputSchema": getattr(t, "inputSchema", None),
        })
    return result


def _call_tool_impl(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke a filesystem tool and return a serializable result dict.

    Imports the ``call_tool`` coroutine from stdio_server and runs it.  The
    stdio_server's ``call_tool`` returns either a plain dict (structured
    content) or an MCP result object.  We normalize to the daemon protocol
    response shape.
    """
    from mcp_servers.system.core.filesystem.stdio_server import call_tool as _call_tool_coro
    result = asyncio.run(_call_tool_coro(tool_name, arguments))

    # The stdio_server call_tool returns a dict (structuredContent body).
    # Wrap it in the daemon protocol response shape.
    if isinstance(result, dict):
        # Produce a text summary from the structured result for the content field.
        content_text = json.dumps(result, indent=2, default=str)
        return {
            "content": content_text,
            "isError": False,
            "structuredContent": result,
        }
    # Fallback for unexpected return types.
    return {
        "content": str(result),
        "isError": False,
        "structuredContent": None,
    }


def handle_request(raw_request: str) -> str:
    """Parse a JSON request, dispatch it, and return a JSON response line."""
    try:
        req = json.loads(raw_request)
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"malformed JSON: {e}"})

    kind = req.get("kind")

    try:
        if kind == "list_tools":
            tools = _build_tool_list()
            return json.dumps({"ok": True, "payload": tools})

        if kind == "call_tool":
            tool_name = req.get("tool_name", "")
            arguments = req.get("arguments", {})
            result = _call_tool_impl(tool_name, arguments)
            return json.dumps({"ok": True, "payload": result}, default=str)

        return json.dumps({"ok": False, "error": f"unknown request kind: {kind!r}"})

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[filesystem-daemon] error handling {kind}: {e}\n{tb}", flush=True)
        return json.dumps({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Socket server — real request/response (phase 3)
# ---------------------------------------------------------------------------


_MAX_REQUEST_BYTES = 1 * 1024 * 1024  # 1 MiB — generous for any tool request


def serve_filesystem_socket_forever(config: dict[str, Any]) -> None:
    """Unix-socket server that dispatches real list_tools/call_tool requests.

    Uses a request-per-connection model: each client connects, sends one
    newline-terminated JSON request, and receives one JSON response.  This
    is an ORBIT-local daemon bridge protocol, not standard MCP.
    """
    sock_path = Path(config["socket_path"])

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(str(sock_path))
    # Restrict socket to owner-only access.
    os.chmod(str(sock_path), 0o600)
    srv.listen(8)
    srv.settimeout(1.0)  # periodic interrupt check

    print(f"[filesystem-daemon] listening on {sock_path} (pid={os.getpid()})", flush=True)

    while not _shutdown_requested:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        try:
            conn.settimeout(30.0)
            # Read the full request (client shuts down write side when done).
            chunks: list[bytes] = []
            total = 0
            oversized = False
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                chunks.append(data)
                total += len(data)
                if total > _MAX_REQUEST_BYTES:
                    oversized = True
                    break
            if oversized:
                err = json.dumps({"ok": False, "error": "request too large"})
                conn.sendall(err.encode("utf-8"))
            else:
                raw = b"".join(chunks).decode("utf-8").strip()
                if raw:
                    response = handle_request(raw)
                    conn.sendall(response.encode("utf-8"))
        except Exception as e:
            print(f"[filesystem-daemon] connection error: {e}", flush=True)
            try:
                err_resp = json.dumps({"ok": False, "error": str(e)})
                conn.sendall(err_resp.encode("utf-8"))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, frame: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print(f"[filesystem-daemon] received signal {signum}, shutting down", flush=True)


def main() -> None:
    config = load_server_config_from_env()

    sock_path = Path(config["socket_path"])

    # Ensure the workspace-local runtime directory exists (socket, meta, log).
    from orbit.runtime.mcp.daemon_paths import ensure_orbit_mcp_runtime_dir
    ensure_orbit_mcp_runtime_dir(config["workspace_root"])

    # Clean stale socket if present.
    remove_existing_socket_if_stale(sock_path)

    # Write the meta sidecar so lifecycle helpers can read our identity.
    write_filesystem_daemon_meta(config)

    # Register cleanup for normal exit.
    atexit.register(cleanup_filesystem_daemon_runtime, config)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Serve.
    serve_filesystem_socket_forever(config)


if __name__ == "__main__":
    main()
