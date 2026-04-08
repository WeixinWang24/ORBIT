from __future__ import annotations

import json
import os
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
    resolve_workspace_root,
)
from orbit.runtime.diagnostics.subprocess_utils import run_bounded_subprocess
from orbit.runtime.diagnostics.text_utils import preferred_raw_output, truncate_text

SERVER_NAME = "ruff"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 180
MAX_ISSUES_RETURNED = 200
MAX_RAW_OUTPUT_CHARS = 8000


def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    return resolve_workspace_root(raw)


def _build_ruff_command(
    *,
    workspace_root: Path,
    paths: list[str] | None,
    select: list[str] | None,
    ignore: list[str] | None,
) -> list[str]:
    binary = shutil.which("ruff")
    if not binary:
        raise RuntimeError("ruff binary not found in current environment")
    cmd = [binary, "check", "--output-format", "json"]
    if select:
        cmd.extend(["--select", ",".join(item for item in select if isinstance(item, str) and item.strip())])
    if ignore:
        cmd.extend(["--ignore", ",".join(item for item in ignore if isinstance(item, str) and item.strip())])
    resolved_paths = [str(p) for p in resolve_workspace_child_paths(workspace_root=workspace_root, raw_paths=paths)]
    if resolved_paths:
        cmd.extend(resolved_paths)
    else:
        cmd.append(str(workspace_root))
    return cmd


def _rule_family(code: str | None) -> str | None:
    if not code or not isinstance(code, str):
        return None
    prefix = ""
    for ch in code:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix or None


def _normalize_ruff_issue(item: dict[str, Any]) -> dict[str, Any]:
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    end_location = item.get("end_location") if isinstance(item.get("end_location"), dict) else {}
    code = item.get("code") if isinstance(item.get("code"), str) else None
    return {
        "path": str(item.get("filename") or ""),
        "line": location.get("row"),
        "column": location.get("column"),
        "end_line": end_location.get("row"),
        "end_column": end_location.get("column"),
        "code": code,
        "message": str(item.get("message") or ""),
        "severity": "error",
        "rule_family": _rule_family(code),
    }


def classify_ruff_outcome(
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
            "failure_layer": "static_analysis",
            "failure_kind": "lint_findings",
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
        "failure_kind": "ruff_execution_error",
    }


def invoke_ruff(
    *,
    workspace_root: Path,
    paths: list[str] | None = None,
    select: list[str] | None = None,
    ignore: list[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    effective_timeout = min(float(timeout_seconds), float(MAX_TIMEOUT_SECONDS))
    cmd = _build_ruff_command(
        workspace_root=workspace_root,
        paths=paths,
        select=select,
        ignore=ignore,
    )
    selection_basis = "paths" if paths else "workspace_default"
    invocation = {
        "cwd": str(workspace_root),
        "workspace_root": str(workspace_root),
        "paths": paths or [],
        "select": select or [],
        "ignore": ignore or [],
        "timeout_seconds": effective_timeout,
        "selection_basis": selection_basis,
        "command": " ".join(cmd),
    }

    execution = run_bounded_subprocess(
        cmd=cmd,
        cwd=workspace_root,
        timeout_seconds=effective_timeout,
    )
    stdout = execution["stdout"]
    stderr = execution["stderr"]
    raw_text = preferred_raw_output(stdout=stdout, stderr=stderr)

    if execution["timed_out"]:
        raw_excerpt, raw_truncated = truncate_text(raw_text, MAX_RAW_OUTPUT_CHARS)
        classification = classify_ruff_outcome(
            exit_code=None,
            timed_out=True,
            issues_total=0,
            raw_output=raw_text,
        )
        return {
            "result_kind": "ruff_structured",
            "diagnostic_kind": "static_analysis",
            "outcome_kind": classification["outcome_kind"],
            "failure_layer": classification["failure_layer"],
            "failure_kind": classification["failure_kind"],
            "success": classification["success"],
            "issues": [],
            "issues_total": 0,
            "issues_truncated": False,
            "raw_output_excerpt": raw_excerpt,
            "raw_output_truncated": raw_truncated,
            "invocation": invocation,
        }

    try:
        parsed_json = json.loads(stdout or "[]")
        parsed_items = parsed_json if isinstance(parsed_json, list) else []
    except json.JSONDecodeError:
        parsed_items = []
    issues_all = [_normalize_ruff_issue(item) for item in parsed_items if isinstance(item, dict)]
    issues = issues_all[:MAX_ISSUES_RETURNED]
    classification = classify_ruff_outcome(
        exit_code=execution["exit_code"],
        timed_out=False,
        issues_total=len(issues_all),
        raw_output=raw_text,
    )
    raw_excerpt, raw_truncated = truncate_text(raw_text, MAX_RAW_OUTPUT_CHARS)
    return {
        "result_kind": "ruff_structured",
        "diagnostic_kind": "static_analysis",
        "outcome_kind": classification["outcome_kind"],
        "failure_layer": classification["failure_layer"],
        "failure_kind": classification["failure_kind"],
        "success": classification["success"],
        "issues": issues,
        "issues_total": len(issues_all),
        "issues_truncated": len(issues_all) > MAX_ISSUES_RETURNED,
        "raw_output_excerpt": raw_excerpt,
        "raw_output_truncated": raw_truncated,
        "invocation": invocation,
    }


server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Workspace-scoped structured Ruff diagnostics MCP server for ORBIT. "
        "Provides run_ruff_structured for bounded static-analysis diagnostics."
    ),
)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_ruff_structured",
            description=(
                "Run Ruff static analysis in the ORBIT workspace and return a structured result "
                "with bounded issues, stable diagnostics taxonomy, and invocation metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "select": {"type": "array", "items": {"type": "string"}},
                    "ignore": {"type": "array", "items": {"type": "string"}},
                    "timeout_seconds": {"type": "number"},
                },
                "required": [],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name != "run_ruff_structured":
        raise ValueError(f"unknown tool: {name}")

    result = invoke_ruff(
        workspace_root=_workspace_root(),
        paths=arguments.get("paths") or None,
        select=arguments.get("select") or None,
        ignore=arguments.get("ignore") or None,
        timeout_seconds=float(arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
    )

    outcome = result["outcome_kind"]
    if outcome == "passed":
        text_summary = "ruff passed"
    elif outcome == "issues_found":
        text_summary = f"ruff found {result['issues_total']} issues"
    elif outcome == "timeout":
        text_summary = "ruff timed out"
    elif outcome == "usage_error":
        text_summary = "ruff usage error"
    else:
        text_summary = "ruff execution error"

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
