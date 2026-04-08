from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from orbit.runtime.process.service import ProcessService
from orbit.store.sqlite_store import SQLiteStore

SERVER_NAME = "process"
SERVER_VERSION = "0.2.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
PROCESS_DB_PATH_ENV = "ORBIT_PROCESS_DB_PATH"
DEFAULT_READ_MAX_CHARS = 12000

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    # Task-backed persistent process identity: process handles survive MCP server restarts.
    # Lifecycle truth is grounded in persisted files (runner status file, stdout/stderr files,
    # store record), not in server-local in-memory state. A fresh server instance re-derives
    # full process state from those persisted artifacts on each tool call.
    instructions="Workspace-scoped MCP server for task-backed persistent process lifecycle management. Process identity and output continuity are grounded in persisted runner status and output files, not MCP session state.",
)


def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def _process_db_path() -> Path:
    raw = os.environ.get(PROCESS_DB_PATH_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {PROCESS_DB_PATH_ENV}")
    path = Path(raw).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _service() -> ProcessService:
    store = SQLiteStore(_process_db_path())
    return ProcessService(store=store, workspace_root=str(_workspace_root()))


def _process_to_dict(process) -> dict[str, Any]:
    return process.model_dump(mode="json") if hasattr(process, "model_dump") else dict(process)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="start_process",
            description=(
                "Start a non-interactive workspace-scoped background process and return a "
                "task-backed persistent process handle. The handle survives MCP server restarts; "
                "lifecycle truth is recovered from the runner status file and persisted output files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    # session_id grounds the process to the owning ORBIT session, enabling
                    # cross-session process retrieval. SessionManager injects it automatically;
                    # the model should not supply it.
                    "session_id": {"type": "string", "description": "ORBIT session that owns this process. Injected by SessionManager — do not supply from the model side."},
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="read_process_output",
            description="Read incremental stdout/stderr from a task-backed persistent process. Output is read from persisted files by offset; continuity survives MCP server restarts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="wait_process",
            description="Wait for a task-backed persistent process to complete or timeout. Terminal state is determined from the runner status file (primary truth), not in-memory session state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="terminate_process",
            description="Terminate a running task-backed persistent process by process_id. Termination is reconciled against the runner status file (primary truth), not an optimistic local write.",
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    service = _service()

    if name == "start_process":
        session_id = arguments.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        process = service.start_process(
            session_id=session_id,
            command=arguments.get("command"),
            cwd=arguments.get("cwd"),
        )
        result = _process_to_dict(process)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=False,
        )

    process_id = arguments.get("process_id")
    if not isinstance(process_id, str) or not process_id.strip():
        raise ValueError("process_id must be a non-empty string")

    if name == "read_process_output":
        result = service.read_output_delta(process_id, max_chars=arguments.get("max_chars") or DEFAULT_READ_MAX_CHARS)
        payload = {
            "process": _process_to_dict(result["process"]),
            "stdout_delta": result["stdout_delta"],
            "stderr_delta": result["stderr_delta"],
            "stdout_has_more": result["stdout_has_more"],
            "stderr_has_more": result["stderr_has_more"],
            "stdout_original_chars": result["stdout_original_chars"],
            "stderr_original_chars": result["stderr_original_chars"],
            "stdout_offset_before": result["stdout_offset_before"],
            "stderr_offset_before": result["stderr_offset_before"],
            "stdout_offset_after": result["stdout_offset_after"],
            "stderr_offset_after": result["stderr_offset_after"],
        }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result["stdout_delta"] or result["stderr_delta"] or "")],
            structuredContent=payload,
            isError=False,
        )

    if name == "wait_process":
        result = service.wait_process(process_id, timeout_seconds=float(arguments.get("timeout_seconds", 30.0)))
        payload = {
            "process": _process_to_dict(result["process"]),
            "timed_out": result["timed_out"],
        }
        if result["timed_out"]:
            payload["failure_layer"] = "runtime_execution"
            payload["failure_kind"] = "timeout"
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structuredContent=payload,
            isError=result["timed_out"],
        )

    if name == "terminate_process":
        process = service.terminate_process(process_id)
        payload = {
            "process": _process_to_dict(process),
            "terminated": True,
            "termination_status": process.status,
            "exit_code": process.exit_code,
        }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structuredContent=payload,
            isError=False,
        )

    raise ValueError(f"unknown tool: {name}")


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
