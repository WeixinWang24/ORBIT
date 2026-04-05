from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from orbit.browser_manager import BrowserManager

SERVER_NAME = "browser"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions="Workspace-scoped MCP browser verification and light-interaction server for ORBIT core capabilities.",
)

_MANAGER: BrowserManager | None = None


def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def _manager() -> BrowserManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = BrowserManager(_workspace_root())
    return _MANAGER


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="browser_open",
            description="Open a URL in the current browser session and make it the active page.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_snapshot",
            description="Return a bounded structured snapshot of the current page.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_click",
            description="Click an element on the current page by snapshot-local element id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "element_id": {"type": "string"},
                },
                "required": ["element_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_type",
            description="Fill an input/textarea on the current page by snapshot-local element id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "element_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["element_id", "text"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_console",
            description="Return a bounded buffer of recent browser console messages.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_screenshot",
            description="Capture a PNG screenshot artifact of the current page.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    manager = _manager()

    if name == "browser_open":
        result = manager.open(arguments.get("url"))
    elif name == "browser_snapshot":
        result = manager.snapshot()
    elif name == "browser_click":
        result = manager.click(arguments.get("element_id"))
    elif name == "browser_type":
        result = manager.type(arguments.get("element_id"), arguments.get("text"))
    elif name == "browser_console":
        result = manager.console()
    elif name == "browser_screenshot":
        result = manager.screenshot()
    else:
        raise ValueError(f"unknown tool: {name}")

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
        structuredContent=result,
        isError=False,
    )


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )


if __name__ == "__main__":
    anyio.run(main)
