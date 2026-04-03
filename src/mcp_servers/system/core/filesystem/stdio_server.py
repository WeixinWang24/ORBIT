from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

SERVER_NAME = "filesystem"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
MAX_READ_BYTES_ENV = "ORBIT_MCP_MAX_READ_BYTES"
DEFAULT_MAX_READ_BYTES = 64 * 1024

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions="Workspace-scoped filesystem MCP server for ORBIT core capabilities.",
)


def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def _max_read_bytes() -> int:
    raw = os.environ.get(MAX_READ_BYTES_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_READ_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer for {MAX_READ_BYTES_ENV}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_READ_BYTES_ENV} must be > 0")
    return value


def _resolve_safe_file_path(path: str) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")

    workspace_root = _workspace_root()
    target = (workspace_root / candidate).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path escapes workspace") from exc
    if not target.exists():
        raise ValueError("file not found")
    if not target.is_file():
        raise ValueError("path is not a file")
    return target


def _read_file_result(path: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    max_read_bytes = _max_read_bytes()
    raw = target.read_bytes()
    truncated = len(raw) > max_read_bytes
    payload = raw[:max_read_bytes]
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        content = payload.decode("utf-8", errors="replace")
    return {
        "path": path,
        "content": content,
        "truncated": truncated,
        "bytes_read": len(payload),
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Read a UTF-8 text file from the ORBIT workspace using a workspace-relative path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path, for example notes/read_smoke.txt",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "read_file":
        raise ValueError(f"unknown tool: {name}")
    path = arguments.get("path")
    return _read_file_result(path)


async def main() -> None:
    _workspace_root()
    _max_read_bytes()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
            ),
        )


if __name__ == "__main__":
    anyio.run(main)
