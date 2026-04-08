from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from orbit.runtime.diagnostics.path_utils import (
    resolve_workspace_child_paths,
    resolve_workspace_optional_file,
    resolve_workspace_root,
)
from orbit.runtime.diagnostics.subprocess_utils import run_bounded_subprocess
from orbit.runtime.diagnostics.text_utils import truncate_text

SERVER_NAME = "mypy"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300
MAX_ISSUES_RETURNED = 200
MAX_RAW_OUTPUT_CHARS = 8000

_MYPY_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<column>\d+))?:\s+(?P<severity>error|note):\s+(?P<message>.*?)(?:\s{2,}\[(?P<code>[^\]]+)\])?$"
)


def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    return resolve_workspace_root(raw)


def _build_mypy_command(
    *,
    workspace_root: Path,
    paths: list[str] | None,
    config_file: str | None,
    strict: bool | None,
) -> list[str]:
    binary = shutil.which("mypy")
    if not binary:
        raise RuntimeError("mypy binary not found in current environment")
    cmd = [binary]
    resolved_config = resolve_workspace_optional_file(workspace_root=workspace_root, raw_path=config_file)
    if resolved_config:
        cmd.extend(["--config-file", str(resolved_config)])
    if strict is True:
        cmd.append("--strict")
    resolved_paths = [str(p) for p in resolve_workspace_child_paths(workspace_root=workspace_root, raw_paths=paths)]
    if resolved_paths:
        cmd.extend(resolved_paths)
    else:
        cmd.append(str(workspace_root))
    return cmd


def _parse_mypy_issue_line(line: str) -> dict[str, Any] | None:
    match = _MYPY_LINE_RE.match(line.strip())
    if not match:
        return None
    column = match.group("column")
    return {
        "path": match.group("path"),
        "line": int(match.group("line")),
        "column": int(column) if column is not None else None,
        "severity": match.group("severity"),
        "message": match.group("message"),
        "error_code": match.group("code"),
    }


def _parse_mypy_output(stdout: str, stderr: str) -> dict[str, Any]:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    issues_all = []
    for line in combined.splitlines():
        issue = _parse_mypy_issue_line(line)
        if issue is not None:
            issues_all.append(issue)
    issues = issues_all[:MAX_ISSUES_RETURNED]
    raw_excerpt, raw_truncated = truncate_text(combined, MAX_RAW_OUTPUT_CHARS)
    return {
        "issues": issues,
        "issues_total": len(issues_all),
        "issues_truncated": len(issues_all) > MAX_ISSUES_RETURNED,
        "raw_output_excerpt": raw_excerpt,
        "raw_output_truncated": raw_truncated,
    }


def classify_mypy_outcome(
    *,
    exit_code: int | None,
    timed_out: bool,
    issues_total: int,
    raw_output: str,
) -> dict[str, Any]:
    if timed_out:
        return {
            "success": False,
            "outcome_kind": "timeout",
            "failure_layer": "runtime_execution",
            "failure_kind": "timeout",
        }
    if exit_code == 0:
        return {
            "success": True,
            "outcome_kind": "passed",
            "failure_layer": "none",
            "failure_kind": "none",
        }
    if exit_code == 1 and issues_total > 0:
        return {
            "success": False,
            "outcome_kind": "issues_found",
            "failure_layer": "type_analysis",
            "failure_kind": "type_errors",
        }
    if exit_code == 2:
        return {
            "success": False,
            "outcome_kind": "usage_error",
            "failure_layer": "tool_invocation",
            "failure_kind": "usage_error",
        }
    return {
        "success": False,
        "outcome_kind": "tool_error",
        "failure_layer": "tool_invocation",
        "failure_kind": "mypy_execution_error",
    }


def invoke_mypy(
    *,
    workspace_root: Path,
    paths: list[str] | None = None,
    config_file: str | None = None,
    strict: bool | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    effective_timeout = min(float(timeout_seconds), float(MAX_TIMEOUT_SECONDS))
    cmd = _build_mypy_command(
        workspace_root=workspace_root,
        paths=paths,
        config_file=config_file,
        strict=strict,
    )
    invocation = {
        "cwd": str(workspace_root),
        "workspace_root": str(workspace_root),
        "paths": paths or [],
        "config_file": config_file,
        "strict": strict,
        "timeout_seconds": effective_timeout,
        "selection_basis": "paths" if paths else "workspace_default",
        "command": " ".join(cmd),
    }

    execution = run_bounded_subprocess(
        cmd=cmd,
        cwd=workspace_root,
        timeout_seconds=effective_timeout,
    )
    parsed = _parse_mypy_output(execution["stdout"], execution["stderr"])
    classification = classify_mypy_outcome(
        exit_code=execution["exit_code"],
        timed_out=execution["timed_out"],
        issues_total=parsed["issues_total"],
        raw_output=parsed["raw_output_excerpt"],
    )
    return {
        "result_kind": "mypy_structured",
        "diagnostic_kind": "type_analysis",
        "outcome_kind": classification["outcome_kind"],
        "failure_layer": classification["failure_layer"],
        "failure_kind": classification["failure_kind"],
        "success": classification["success"],
        **parsed,
        "invocation": invocation,
    }


server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Workspace-scoped structured mypy diagnostics MCP server for ORBIT. "
        "Provides run_mypy_structured for bounded type-analysis diagnostics."
    ),
)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_mypy_structured",
            description=(
                "Run mypy in the ORBIT workspace and return a structured result with bounded issues, "
                "stable diagnostics taxonomy, and invocation metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "config_file": {"type": "string"},
                    "strict": {"type": "boolean"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": [],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name != "run_mypy_structured":
        raise ValueError(f"unknown tool: {name}")
    result = invoke_mypy(
        workspace_root=_workspace_root(),
        paths=arguments.get("paths") or None,
        config_file=arguments.get("config_file") or None,
        strict=arguments.get("strict"),
        timeout_seconds=float(arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
    )

    outcome = result["outcome_kind"]
    if outcome == "passed":
        text_summary = "mypy passed"
    elif outcome == "issues_found":
        text_summary = f"mypy found {result['issues_total']} issues"
    elif outcome == "timeout":
        text_summary = "mypy timed out"
    elif outcome == "usage_error":
        text_summary = "mypy usage error"
    else:
        text_summary = "mypy execution error"

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text_summary)],
        structuredContent=result,
        isError=not result["success"],
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
