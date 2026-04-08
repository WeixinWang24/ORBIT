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
    # Live-host substrate: all tools operate against the same persistent browser session
    # managed by a single long-lived BrowserManager in this server process. Snapshot-local
    # element IDs (from browser_snapshot) are valid targets for click/type only within the
    # same live session. Correctness depends on host process continuity — a restarted server
    # starts a fresh browser context, losing all prior navigation, DOM state, and element IDs.
    instructions=(
        "Live-host substrate MCP server for ORBIT browser automation. "
        "All tools share a single persistent browser session backed by a long-lived BrowserManager. "
        "Snapshot-local element IDs from browser_snapshot are valid for click and type operations "
        "only within the same live session. Host process continuity is required for correctness."
    ),
)

# _MANAGER is the live browser host singleton for this server process. All tool calls
# route through this single BrowserManager instance, which is why snapshot-local element
# IDs from browser_snapshot remain valid targets for browser_click and browser_type —
# they reference live DOM state in the same persistent session. A restarted server process
# creates a new BrowserManager and a fresh browser context, invalidating all prior element
# IDs. This is the architectural reason continuity_mode is persistent_required for this family.
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
            description=(
                "Navigate the live browser session to a URL, replacing the current page. "
                "Prior element IDs are invalidated; take a new browser_snapshot after opening."
            ),
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
            description=(
                "Return a bounded structured snapshot of the current live page state. "
                "Element IDs in the result are snapshot-local handles valid for browser_click "
                "and browser_type within this same live session."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_click",
            description=(
                "Click an element on the current live page by snapshot-local element_id. "
                "The element_id must come from a prior browser_snapshot in the same live session; "
                "IDs from a different session or after a page navigation are not valid."
            ),
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
            description=(
                "Type text into an input or textarea on the current live page by snapshot-local element_id. "
                "The element_id must come from a prior browser_snapshot in the same live session."
            ),
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
            description=(
                "Return a bounded buffer of browser console messages accumulated in the live session. "
                "Messages are captured from the persistent session; a restarted server loses prior console history."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="browser_screenshot",
            description="Capture a PNG screenshot of the current live page state.",
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
