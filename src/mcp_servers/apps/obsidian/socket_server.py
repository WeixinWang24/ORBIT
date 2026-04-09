"""Obsidian MCP daemon -- independent long-lived socket server process.

Daemon transport for the Obsidian capability family
----------------------------------------------------
This script runs as a standalone process, independently of the ORBIT CLI.
It binds a Unix domain socket inside the workspace runtime directory and
serves real ``list_tools`` / ``call_tool`` requests over a simple
newline-delimited JSON protocol.

**This is an ORBIT-local daemon bridge protocol, not standard MCP.**
See ``orbit.runtime.mcp.socket_protocol`` for the wire format spec.
The protocol is request-per-connection: the client connects, sends one
JSON-line request, and receives one JSON-line response, then the connection
is closed.

The actual Obsidian tool implementations are imported from the existing
``stdio_server`` module so there is a single source of truth.
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
    "ORBIT_OBSIDIAN_VAULT_ROOT",
    "ORBIT_MCP_SOCKET_PATH",
    "ORBIT_MCP_SERVER_INSTANCE_KEY",
}


def load_server_config_from_env() -> dict[str, Any]:
    """Read and validate daemon configuration from environment variables."""
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(sorted(missing))}")

    config: dict[str, Any] = {
        "vault_root": os.environ["ORBIT_OBSIDIAN_VAULT_ROOT"].strip(),
        "workspace_root": os.environ.get("ORBIT_WORKSPACE_ROOT", "").strip() or os.getcwd(),
        "socket_path": os.environ["ORBIT_MCP_SOCKET_PATH"].strip(),
        "server_instance_key": os.environ["ORBIT_MCP_SERVER_INSTANCE_KEY"].strip(),
    }
    return config


# ---------------------------------------------------------------------------
# Meta payload
# ---------------------------------------------------------------------------


def obsidian_daemon_meta_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the metadata sidecar payload for the running daemon."""
    return {
        "server_name": "obsidian",
        "socket_path": config["socket_path"],
        "server_instance_key": config["server_instance_key"],
        "pid": os.getpid(),
        "vault_root": config["vault_root"],
        "workspace_root": config["workspace_root"],
        "started_at": time.time(),
    }


def write_obsidian_daemon_meta(config: dict[str, Any]) -> None:
    """Write the daemon metadata sidecar JSON file."""
    ws = config["workspace_root"]
    from orbit.runtime.mcp.daemon_paths import obsidian_meta_path

    meta_path = obsidian_meta_path(ws)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = obsidian_daemon_meta_payload(config)
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


def cleanup_obsidian_daemon_runtime(config: dict[str, Any]) -> None:
    """Best-effort removal of socket and meta on shutdown."""
    for key in ("socket_path",):
        p = Path(config.get(key, ""))
        try:
            p.unlink()
        except (FileNotFoundError, OSError):
            pass

    try:
        from orbit.runtime.mcp.daemon_paths import obsidian_meta_path
        obsidian_meta_path(config["workspace_root"]).unlink()
    except (FileNotFoundError, OSError):
        pass


# ---------------------------------------------------------------------------
# Request dispatch -- reuses real Obsidian tool implementations
# ---------------------------------------------------------------------------


def _build_tool_list() -> list[dict[str, Any]]:
    """Return the Obsidian tool descriptors as plain dicts.

    Imports the ``list_tools`` coroutine from stdio_server and runs it once
    to get the canonical tool list.  The coroutine is pure metadata and does
    not touch event-loop state, so a single ``asyncio.run`` at startup is safe.
    """
    from mcp_servers.apps.obsidian.stdio_server import list_tools as _list_tools_coro
    tools = asyncio.run(_list_tools_coro())
    result: list[dict[str, Any]] = []
    for t in tools:
        result.append({
            "name": t.name,
            "description": getattr(t, "description", None),
            "inputSchema": getattr(t, "inputSchema", None),
        })
    return result


# Cache tool list at module scope after first build.
_CACHED_TOOL_LIST: list[dict[str, Any]] | None = None


def _get_tool_list() -> list[dict[str, Any]]:
    """Return cached tool list, building it on first call."""
    global _CACHED_TOOL_LIST
    if _CACHED_TOOL_LIST is None:
        _CACHED_TOOL_LIST = _build_tool_list()
    return _CACHED_TOOL_LIST


def _call_tool_impl(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke an Obsidian tool and return a serializable result dict.

    Calls the underlying sync ``_*_result`` functions directly from the
    stdio_server module, avoiding repeated ``asyncio.run()`` overhead.
    The Obsidian tools are pure-sync filesystem operations wrapped in
    async decorators; we bypass the async layer here for daemon dispatch.
    """
    from mcp_servers.apps.obsidian.stdio_server import (
        _list_notes_result,
        _read_note_result,
        _search_notes_result,
        _get_note_links_result,
        _get_vault_metadata_result,
        _check_availability_result,
    )

    dispatch = {
        "obsidian_list_notes": lambda args: _list_notes_result(
            args.get("path"), bool(args.get("recursive", False)), args.get("maxResults"),
        ),
        "obsidian_read_note": lambda args: _read_note_result(
            args.get("path"), args.get("includeRawContent"), args.get("maxChars"),
        ),
        "obsidian_search_notes": lambda args: _search_notes_result(
            args.get("query"), args.get("path"), args.get("maxResults"), args.get("searchIn"),
        ),
        "obsidian_get_note_links": lambda args: _get_note_links_result(
            args.get("path"),
        ),
        "obsidian_get_vault_metadata": lambda args: _get_vault_metadata_result(
            args.get("path"), args.get("includeTopLevelEntries"), args.get("maxEntries"),
        ),
        "obsidian_check_availability": lambda args: _check_availability_result(),
    }

    handler = dispatch.get(tool_name)
    if handler is None:
        raise ValueError(f"unknown tool: {tool_name}")

    result = handler(arguments)

    if isinstance(result, dict):
        content_text = json.dumps(result, indent=2, default=str)
        return {
            "content": content_text,
            "isError": False,
            "structuredContent": result,
        }
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
            tools = _get_tool_list()
            return json.dumps({"ok": True, "payload": tools})

        if kind == "call_tool":
            tool_name = req.get("tool_name", "")
            arguments = req.get("arguments", {})
            result = _call_tool_impl(tool_name, arguments)
            return json.dumps({"ok": True, "payload": result}, default=str)

        return json.dumps({"ok": False, "error": f"unknown request kind: {kind!r}"})

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[obsidian-daemon] error handling {kind}: {e}\n{tb}", flush=True)
        return json.dumps({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Socket server -- real request/response
# ---------------------------------------------------------------------------


_MAX_REQUEST_BYTES = 1 * 1024 * 1024  # 1 MiB


def serve_obsidian_socket_forever(config: dict[str, Any]) -> None:
    """Unix-socket server that dispatches real list_tools/call_tool requests.

    Uses a request-per-connection model: each client connects, sends one
    newline-terminated JSON request, and receives one JSON response.  This
    is an ORBIT-local daemon bridge protocol, not standard MCP.
    """
    sock_path = Path(config["socket_path"])

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(str(sock_path))
    os.chmod(str(sock_path), 0o600)
    srv.listen(8)
    srv.settimeout(1.0)

    # Write meta sidecar *after* the socket is bound and listening, so the
    # lifecycle readiness check (meta exists + socket connectable) is atomic.
    write_obsidian_daemon_meta(config)

    print(f"[obsidian-daemon] listening on {sock_path} (pid={os.getpid()})", flush=True)

    while not _shutdown_requested:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        try:
            conn.settimeout(30.0)
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
            print(f"[obsidian-daemon] connection error: {e}", flush=True)
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
    print(f"[obsidian-daemon] received signal {signum}, shutting down", flush=True)


def main() -> None:
    config = load_server_config_from_env()

    sock_path = Path(config["socket_path"])

    from orbit.runtime.mcp.daemon_paths import ensure_orbit_mcp_runtime_dir
    ensure_orbit_mcp_runtime_dir(config["workspace_root"])

    remove_existing_socket_if_stale(sock_path)

    # Meta sidecar is written by serve_obsidian_socket_forever() after socket bind.
    atexit.register(cleanup_obsidian_daemon_runtime, config)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    serve_obsidian_socket_forever(config)


if __name__ == "__main__":
    main()
