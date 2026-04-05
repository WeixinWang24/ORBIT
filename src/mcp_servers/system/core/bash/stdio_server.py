from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from orbit.runtime.mcp.bash_classification import classify_bash_command
from orbit.runtime.mcp.subprocess_env import build_scrubbed_subprocess_env

SERVER_NAME = "bash"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_CHARS = 12000

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions="Workspace-scoped non-interactive bash MCP server for ORBIT core capabilities.",
)

def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def _resolve_cwd(cwd: str | None) -> Path:
    workspace_root = _workspace_root()
    if cwd is None or not str(cwd).strip():
        return workspace_root
    candidate = Path(cwd)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("cwd escapes workspace") from exc
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("cwd is not an existing directory")
    return resolved


def _subprocess_env() -> dict[str, str]:
    return build_scrubbed_subprocess_env()


def _truncate_output(text: str) -> tuple[str, bool, int]:
    if len(text) <= DEFAULT_MAX_OUTPUT_CHARS:
        return text, False, len(text)
    return text[:DEFAULT_MAX_OUTPUT_CHARS], True, len(text)


def _bash_execution_summary(*, exit_code: int | None, timed_out: bool, stderr: str, stdout: str, classification: str) -> tuple[str, bool]:
    if timed_out:
        return "Command timed out before completion.", False
    if exit_code == 0 and not stderr.strip() and not stdout.strip():
        if classification in {"mutating", "ambiguous"}:
            return "Command completed successfully and produced no stdout/stderr output. This is normal for many state-changing shell commands; if explicit confirmation is needed, perform a separate read-only verification step.", True
        return "Command completed successfully with no stdout/stderr output.", False
    if exit_code == 0:
        return "Command completed successfully.", False
    if classification == "read_only" and not stdout.strip() and not stderr.strip():
        return "Command completed with no matching output. For read-only diagnostic commands, this often means the searched resource was not found.", False
    return "Command failed or completed with a non-zero exit code.", False


def _run_bash_result(command: str, cwd: str | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    resolved_cwd = _resolve_cwd(cwd)
    timeout_value = timeout_seconds if isinstance(timeout_seconds, int) and timeout_seconds > 0 else DEFAULT_TIMEOUT_SECONDS
    shell = os.environ.get("SHELL") or "/bin/bash"
    classification, classification_reason = classify_bash_command(command)
    try:
        completed = subprocess.run(
            [shell, "-lc", command],
            cwd=str(resolved_cwd),
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=timeout_value,
        )
        stdout, stdout_truncated, stdout_original = _truncate_output(completed.stdout)
        stderr, stderr_truncated, stderr_original = _truncate_output(completed.stderr)
        execution_summary, verification_suggested = _bash_execution_summary(
            exit_code=completed.returncode,
            timed_out=False,
            stderr=stderr,
            stdout=stdout,
            classification=classification,
        )
        result = {
            "command": command,
            "cwd": str(resolved_cwd),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
            "classification": classification,
            "classification_reason": classification_reason,
            "execution_mode": "direct",
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "stdout_original_chars": stdout_original,
            "stderr_original_chars": stderr_original,
            "execution_summary": execution_summary,
            "verification_suggested": verification_suggested,
        }
        if completed.returncode != 0:
            result["failure_layer"] = "tool_semantic"
            result["failure_kind"] = "nonzero_exit"
        return result
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_truncated, stdout_original = _truncate_output(exc.stdout or "")
        stderr, stderr_truncated, stderr_original = _truncate_output(exc.stderr or "")
        execution_summary, verification_suggested = _bash_execution_summary(
            exit_code=None,
            timed_out=True,
            stderr=stderr,
            stdout=stdout,
            classification=classification,
        )
        return {
            "command": command,
            "cwd": str(resolved_cwd),
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
            "classification": classification,
            "classification_reason": classification_reason,
            "execution_mode": "direct",
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "stdout_original_chars": stdout_original,
            "stderr_original_chars": stderr_original,
            "execution_summary": execution_summary,
            "verification_suggested": verification_suggested,
            "failure_layer": "runtime_execution",
            "failure_kind": "timeout",
        }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_bash",
            description="Run a non-interactive bash command inside the ORBIT workspace and return exit code, stdout, stderr, and timeout status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute via bash -lc."},
                    "cwd": {"type": "string", "description": "Optional workspace-relative working directory."},
                    "timeout_seconds": {"type": "integer", "description": "Optional execution timeout in seconds."},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name != "run_bash":
        raise ValueError(f"unknown tool: {name}")
    result = _run_bash_result(
        command=arguments.get("command"),
        cwd=arguments.get("cwd"),
        timeout_seconds=arguments.get("timeout_seconds"),
    )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result.get("stdout") or result.get("stderr") or "")],
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
