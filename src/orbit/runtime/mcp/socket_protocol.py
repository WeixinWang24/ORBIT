"""ORBIT-local daemon socket protocol helpers.

Transitional transport for phase 3
-----------------------------------
This module defines a simple newline-delimited JSON request/response protocol
used between ``UnixSocketMcpClient`` and the filesystem daemon socket server.

This is NOT standard MCP.  It is an ORBIT-local bridge protocol scoped to the
filesystem daemon.  A future phase may replace it with MCP-over-unix-socket if
the MCP Python SDK adds direct support, or with a more general transport.

Wire format
~~~~~~~~~~~
- Each message is a single JSON object terminated by ``\\n``.
- The client sends one request, the server sends one response, then the
  connection is closed (request-per-connection model).

Request kinds::

    {"kind": "list_tools"}
    {"kind": "call_tool", "tool_name": "...", "arguments": {...}}

Response shape::

    {"ok": true,  "payload": <kind-specific data>}
    {"ok": false, "error": "human-readable error message"}

For ``list_tools``, ``payload`` is a list of tool descriptor dicts::

    [{"name": "read_file", "description": "...", "inputSchema": {...}}, ...]

For ``call_tool``, ``payload`` is::

    {"content": "text output", "isError": false, "structuredContent": {...} | null}
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

# Maximum response size we'll read (16 MiB — generous for tool output).
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def send_request(socket_path: str | Path, request: dict[str, Any], *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Send a JSON request to the daemon and return the parsed JSON response.

    Uses a fresh connection per request (request-per-connection model).
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        sock.connect(str(socket_path))
        # Send request as a single newline-terminated JSON line.
        payload = json.dumps(request, separators=(",", ":")) + "\n"
        sock.sendall(payload.encode("utf-8"))
        # Signal that we're done sending so the server knows the request is complete.
        sock.shutdown(socket.SHUT_WR)
        # Read the full response.
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise RuntimeError("daemon response exceeded maximum size")
        raw = b"".join(chunks)
        if not raw:
            raise RuntimeError("daemon returned empty response")
        return json.loads(raw)
    finally:
        sock.close()
