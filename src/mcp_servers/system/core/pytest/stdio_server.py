"""
ORBIT structured pytest diagnostics MCP server.

Provides a single tool: run_pytest_structured

This is ORBIT's first structured diagnostics first slice. It executes pytest in a
workspace-scoped subprocess and returns a structured result: summary counts, bounded
failure records with node IDs and excerpts, and honest parse-confidence signalling.

It sits between raw shell execution (run_bash) and a future broader diagnostics family.
It is not a full CI orchestration system.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from orbit.runtime.mcp.subprocess_env import build_scrubbed_subprocess_env

SERVER_NAME = "pytest"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"

# Execution bounds
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300

# Output bounds
MAX_FAILURES_RETURNED = 20       # max failure records in structured output
MAX_EXCERPT_CHARS = 2000         # max chars per individual failure excerpt
MAX_RAW_OUTPUT_CHARS = 8000      # max chars for raw_output_excerpt field

# Pytest exit codes (stable across pytest >= 6)
_EXIT_OK = 0              # all tests passed (or no tests + no error)
_EXIT_TESTSFAILED = 1     # one or more tests failed or raised an error
_EXIT_INTERRUPTED = 2     # execution interrupted (e.g., keyboard interrupt)
_EXIT_INTERNALERROR = 3   # pytest internal error
_EXIT_USAGEERROR = 4      # bad command-line usage
_EXIT_NOTESTSCOLLECTED = 5  # no tests were collected

# ─── Parser ───────────────────────────────────────────────────────────────────
# All parse_* functions are pure text→data transforms and are intentionally
# importable for direct unit testing without the MCP server.

_RE_COLLECTED = re.compile(r'collected\s+(\d+)\s+items?')
_RE_NOTESTSCOLLECTED = re.compile(r'no tests ran|collected\s+0\s+items?', re.IGNORECASE)
_RE_DURATION = re.compile(r'\bin\s+([\d.]+)s\b')
_RE_COUNT = {
    "passed":   re.compile(r'(\d+)\s+passed'),
    "failed":   re.compile(r'(\d+)\s+failed'),
    "skipped":  re.compile(r'(\d+)\s+skipped'),
    "errors":   re.compile(r'(\d+)\s+error'),
    "warnings": re.compile(r'(\d+)\s+warning'),
}
# Short summary lines: "FAILED tests/foo.py::test_bar - AssertionError: ..."
_RE_SHORT_SUMMARY_ITEM = re.compile(
    r'^(?P<status>FAILED|ERROR)\s+(?P<node_id>\S+?)(?:\s+-\s+(?P<reason>.+))?$',
    re.MULTILINE,
)
# Section separators: "===..." and "___..."
_RE_SECTION_BOUNDARY = re.compile(r'^={5,}.*?={5,}\s*$', re.MULTILINE)
_RE_FAILURE_BLOCK_HEADER = re.compile(r'^_{5,}\s*(.*?)\s*_{5,}\s*$', re.MULTILINE)


def parse_collected(output: str) -> int | None:
    """Extract the 'collected N items' count from pytest output."""
    m = _RE_COLLECTED.search(output)
    return int(m.group(1)) if m else None


def parse_summary_counts(output: str) -> dict[str, int | None]:
    """
    Extract pass/fail/skip/error/warning counts and duration from the final summary line.
    Returns a dict with keys: passed, failed, skipped, errors, warnings, duration_seconds.
    Any field not found in output is None — honest about what was not parsed.
    """
    result: dict[str, int | float | None] = {k: None for k in ("passed", "failed", "skipped", "errors", "warnings", "duration_seconds")}
    # The summary line is the last line that looks like "=== N failed, M passed in Xs ==="
    # Scan all section boundaries to find one with count keywords.
    candidates = _RE_SECTION_BOUNDARY.findall(output)
    summary_text = ""
    for line in reversed(candidates):
        if any(kw in line for kw in ("passed", "failed", "skipped", "error", "warning", "no tests ran")):
            summary_text = line
            break
    if not summary_text:
        return result
    for key, pattern in _RE_COUNT.items():
        m = pattern.search(summary_text)
        if m:
            result[key] = int(m.group(1))
    dur_m = _RE_DURATION.search(summary_text)
    if dur_m:
        try:
            result["duration_seconds"] = float(dur_m.group(1))
        except ValueError:
            pass
    return result


def parse_short_summary_items(output: str) -> list[dict[str, str]]:
    """
    Extract structured failure/error entries from pytest's 'short test summary info' section.
    Each entry: {"status": "FAILED"|"ERROR", "node_id": "...", "reason": "..."|""}.

    This is the most stable way to extract failure node IDs and one-line reasons.
    """
    # Find the 'short test summary info' section
    short_section_match = re.search(
        r'={5,}\s+short test summary info\s+={5,}(.*?)(?:={5,}|$)',
        output,
        re.DOTALL | re.IGNORECASE,
    )
    if not short_section_match:
        # Fall back: scan the entire output for FAILED/ERROR lines
        search_text = output
    else:
        search_text = short_section_match.group(1)

    items = []
    for m in _RE_SHORT_SUMMARY_ITEM.finditer(search_text):
        items.append({
            "status": m.group("status"),
            "node_id": m.group("node_id").strip(),
            "reason": (m.group("reason") or "").strip(),
        })
    # Deduplicate by node_id, keeping first occurrence
    seen: set[str] = set()
    unique = []
    for item in items:
        if item["node_id"] not in seen:
            seen.add(item["node_id"])
            unique.append(item)
    return unique


def parse_failure_blocks(output: str) -> dict[str, str]:
    """
    Extract the full failure body for each test from the FAILURES and ERRORS sections.
    Returns a dict mapping test name (as it appears in the ___ separator) to its body text.

    This is best-effort: the separator format is stable but may not match the node_id
    exactly in all cases (e.g., parametrized tests). Callers should treat this as
    supplementary to parse_short_summary_items, not a replacement.
    """
    blocks: dict[str, str] = {}

    # Find FAILURES and ERRORS sections (both use the same internal format)
    for section_match in re.finditer(
        r'={5,}\s+(?:FAILURES|ERRORS)\s+={5,}(.*?)(?:={5,}|$)',
        output,
        re.DOTALL | re.IGNORECASE,
    ):
        section_body = section_match.group(1)
        # Split on ___ test_name ___ separators
        parts = _RE_FAILURE_BLOCK_HEADER.split(section_body)
        # parts: ['pre_text', 'test_name1', 'body1', 'test_name2', 'body2', ...]
        for i in range(1, len(parts), 2):
            name = parts[i].strip()
            body = parts[i + 1].strip() if (i + 1) < len(parts) else ""
            if name:
                blocks[name] = body

    return blocks


def _truncate_excerpt(text: str, max_chars: int) -> tuple[str, bool]:
    """Return (truncated_text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def build_failure_records(
    short_items: list[dict[str, str]],
    failure_blocks: dict[str, str],
    *,
    max_failures: int = MAX_FAILURES_RETURNED,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Combine short summary items and full failure blocks into bounded failure records.
    Returns (records, failures_truncated).

    Each record:
    {
        "node_id": str,
        "headline": str,       # one-line reason from short summary; "" if not available
        "excerpt": str,        # bounded failure body; "" if not found in blocks
        "excerpt_truncated": bool,
    }
    """
    total = len(short_items)
    capped = short_items[:max_failures]
    failures_truncated = total > max_failures

    records = []
    for item in capped:
        node_id = item["node_id"]
        headline = item["reason"]

        # Match failure block: the ___ separator uses the test function name, not the
        # full node_id. Try exact match first, then basename match.
        body = failure_blocks.get(node_id, "")
        if not body:
            # Try matching by the last component (function name) of the node_id
            test_name = node_id.split("::")[-1] if "::" in node_id else node_id
            # Also try the parametrized form: test_name[param]
            body = failure_blocks.get(test_name, "")
            if not body:
                # Fuzzy: find a block whose key ends with or contains the test_name
                for block_key, block_body in failure_blocks.items():
                    if test_name in block_key or block_key in node_id:
                        body = block_body
                        break

        excerpt, excerpt_truncated = _truncate_excerpt(body, max_excerpt_chars)
        records.append({
            "node_id": node_id,
            "headline": headline,
            "excerpt": excerpt,
            "excerpt_truncated": excerpt_truncated,
        })

    return records, failures_truncated


def parse_pytest_output(
    stdout: str,
    stderr: str,
    exit_code: int | None,
    *,
    timed_out: bool = False,
) -> dict[str, Any]:
    """
    Parse pytest stdout+stderr into a structured result dict.

    parse_confidence values:
    - "full"    = summary counts and short summary items both parsed
    - "partial" = summary counts parsed but failure details are best-effort or missing
    - "minimal" = only exit code available; text parsing yielded nothing useful
    """
    combined = stdout + "\n" + stderr

    collected = parse_collected(combined)
    counts = parse_summary_counts(combined)
    short_items = parse_short_summary_items(combined)
    failure_blocks = parse_failure_blocks(combined)

    failure_records, failures_truncated = build_failure_records(
        short_items, failure_blocks
    )

    # Determine overall success
    if timed_out:
        success = False
    elif exit_code == _EXIT_OK:
        success = True
    elif exit_code == _EXIT_NOTESTSCOLLECTED:
        success = True  # no tests collected is not a failure; just informational
    else:
        success = False

    # parse_confidence: be honest about what was actually parsed
    got_counts = any(v is not None for v in (counts["passed"], counts["failed"], counts["skipped"], counts["errors"]))
    got_short_items = bool(short_items) or (counts.get("failed") == 0 and counts.get("errors") == 0)
    if got_counts and got_short_items:
        parse_confidence = "full"
    elif got_counts:
        parse_confidence = "partial"
    else:
        parse_confidence = "minimal"

    # Raw output excerpt (bounded)
    raw_text = stdout if stdout.strip() else (stderr if stderr.strip() else "")
    raw_excerpt, raw_truncated = _truncate_excerpt(raw_text, MAX_RAW_OUTPUT_CHARS)

    return {
        "counts": {
            "collected": collected,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "errors": counts["errors"],
            "warnings": counts["warnings"],
            "duration_seconds": counts["duration_seconds"],
        },
        "success": success,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "failures": failure_records,
        "failures_truncated": failures_truncated,
        "failures_total": len(short_items),
        "raw_output_excerpt": raw_excerpt,
        "raw_output_truncated": raw_truncated,
        "parse_confidence": parse_confidence,
    }


# ─── Workspace helpers ────────────────────────────────────────────────────────

def _workspace_root() -> Path:
    raw = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {WORKSPACE_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def _resolve_test_scope(workspace_root: Path, path: str | None) -> str | None:
    """
    Resolve an optional workspace-relative path to an absolute path for pytest.
    Returns None if path is None or empty. Raises ValueError if path escapes workspace.

    Always resolves workspace_root itself before comparison to handle symlinks
    (e.g., macOS /private/var vs /var) that would cause false boundary violations.
    """
    if not path or not str(path).strip():
        return None
    # Resolve workspace_root to eliminate symlinks before comparison.
    workspace_resolved = workspace_root.resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_resolved / candidate).resolve()
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {path!r}") from exc
    return str(resolved)


def _sanitize_targets(targets: list[str] | None) -> list[str]:
    """
    Lightly sanitize explicit pytest node ID targets.
    Rejects targets with shell-unsafe characters or obvious path-escaping.
    Returns a sanitized list safe to pass as pytest CLI arguments.
    """
    if not targets:
        return []
    result = []
    for t in targets:
        if not isinstance(t, str) or not t.strip():
            continue
        # Reject obvious path traversal
        if ".." in t.split("/"):
            raise ValueError(f"target contains path traversal: {t!r}")
        # Reject shell metacharacters that have no place in a node ID
        if any(ch in t for ch in (";", "&", "|", "`", "$", ">")):
            raise ValueError(f"target contains unsafe characters: {t!r}")
        result.append(t.strip())
    return result


# ─── Subprocess invocation ────────────────────────────────────────────────────

def _build_pytest_command(
    *,
    workspace_root: Path,
    path: str | None,
    targets: list[str] | None,
    keyword: str | None,
    max_failures: int | None,
) -> list[str]:
    """Build the pytest invocation command as a list of arguments."""
    cmd = [
        sys.executable, "-m", "pytest",
        "--tb=short",        # bounded tracebacks
        "--no-header",       # skip platform header line
        "-v",                # verbose: per-test PASSED/FAILED lines + node IDs
    ]

    # Test scope: explicit targets take priority over path
    sanitized_targets = _sanitize_targets(targets)
    if sanitized_targets:
        cmd.extend(sanitized_targets)
    elif path:
        resolved = _resolve_test_scope(workspace_root, path)
        if resolved:
            cmd.append(resolved)

    if keyword:
        cmd.extend(["-k", keyword])

    if max_failures and isinstance(max_failures, int) and max_failures > 0:
        cmd.append(f"--maxfail={max_failures}")

    return cmd


def invoke_pytest(
    *,
    workspace_root: Path,
    path: str | None = None,
    targets: list[str] | None = None,
    keyword: str | None = None,
    max_failures: int | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Invoke pytest as a bounded subprocess and return a structured result.
    This function is importable for testing without the MCP server layer.
    """
    cmd = _build_pytest_command(
        workspace_root=workspace_root,
        path=path,
        targets=targets,
        keyword=keyword,
        max_failures=max_failures,
    )
    effective_timeout = min(float(timeout_seconds), float(MAX_TIMEOUT_SECONDS))

    # Use a scrubbed environment: inherit workspace env but strip API keys etc.
    env = build_scrubbed_subprocess_env()
    # Ensure the repo's src/ is on PYTHONPATH so orbit packages resolve.
    repo_root = str(Path(__file__).resolve().parents[4])  # ORBIT root
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(Path(repo_root) / "src")
    env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}" if existing_pythonpath else src_path

    invocation_meta: dict[str, Any] = {
        "cwd": str(workspace_root),
        "path": path,
        "targets": targets or [],
        "keyword": keyword,
        "max_failures": max_failures,
        "command": " ".join(cmd),
    }

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        parsed = parse_pytest_output(
            completed.stdout,
            completed.stderr,
            exit_code=completed.returncode,
            timed_out=False,
        )
        parsed["invocation"] = invocation_meta
        return parsed

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        parsed = parse_pytest_output(
            stdout,
            stderr,
            exit_code=None,
            timed_out=True,
        )
        parsed["invocation"] = invocation_meta
        parsed["failure_layer"] = "runtime_execution"
        parsed["failure_kind"] = "timeout"
        return parsed


# ─── MCP server ───────────────────────────────────────────────────────────────

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Workspace-scoped structured pytest diagnostics MCP server for ORBIT. "
        "Provides run_pytest_structured: executes pytest and returns structured "
        "pass/fail summary, bounded failure records, and honest parse-confidence signalling."
    ),
)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_pytest_structured",
            description=(
                "Run pytest in the ORBIT workspace and return a structured result: "
                "summary counts (passed/failed/skipped/errors), bounded failure records "
                "with test node IDs and excerpts, and a parse_confidence indicator. "
                "Use this instead of run_bash for test-execution diagnostics in coding loops."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional workspace-relative directory or file to scope the pytest run. "
                            "Example: 'tests/' or 'tests/test_foo.py'. "
                            "Ignored if targets is provided."
                        ),
                    },
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional explicit pytest node IDs to run. "
                            "Example: ['tests/test_foo.py::TestClass::test_method']. "
                            "Takes priority over path."
                        ),
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Optional -k expression to select tests by name pattern.",
                    },
                    "max_failures": {
                        "type": "integer",
                        "description": "Optional --maxfail=N to stop after N failures.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": f"Execution timeout in seconds (default {DEFAULT_TIMEOUT_SECONDS}, max {MAX_TIMEOUT_SECONDS}).",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name != "run_pytest_structured":
        raise ValueError(f"unknown tool: {name}")

    workspace_root = _workspace_root()

    path = arguments.get("path") or None
    targets = arguments.get("targets") or None
    keyword = arguments.get("keyword") or None
    max_failures = arguments.get("max_failures") or None
    timeout_raw = arguments.get("timeout_seconds")
    timeout_seconds = float(timeout_raw) if timeout_raw is not None else DEFAULT_TIMEOUT_SECONDS

    result = invoke_pytest(
        workspace_root=workspace_root,
        path=path,
        targets=targets,
        keyword=keyword,
        max_failures=max_failures,
        timeout_seconds=timeout_seconds,
    )

    # Text summary for the content field (human-readable headline)
    summary_parts = []
    if result["timed_out"]:
        summary_parts.append("pytest timed out")
    elif result["success"]:
        p = result["counts"].get("passed")
        summary_parts.append(f"All tests passed" + (f" ({p} passed)" if p is not None else ""))
    else:
        f = result["counts"].get("failed")
        e = result["counts"].get("errors")
        parts = []
        if f:
            parts.append(f"{f} failed")
        if e:
            parts.append(f"{e} error{'s' if e != 1 else ''}")
        summary_parts.append(", ".join(parts) if parts else "Tests failed")

    text_summary = summary_parts[0] if summary_parts else "pytest completed"

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
