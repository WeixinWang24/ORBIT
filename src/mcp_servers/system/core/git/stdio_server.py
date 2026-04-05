from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

SERVER_NAME = "git"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
DEFAULT_MAX_DIFF_CHARS = 12000

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions="Workspace-scoped git MCP server for ORBIT coding-agent read surfaces.",
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
    if cwd is not None and str(cwd).strip():
        candidate = Path(cwd)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not resolved.exists() or not resolved.is_dir():
                raise ValueError("cwd is not an existing directory")
            return resolved
    workspace_root = _workspace_root()
    if cwd is None or not str(cwd).strip():
        return workspace_root
    candidate = Path(cwd)
    resolved = (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("cwd escapes workspace") from exc
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("cwd is not an existing directory")
    return resolved


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=20,
    )


def _truncate(text: str, max_chars: int) -> tuple[str, bool, int]:
    if len(text) <= max_chars:
        return text, False, len(text)
    return text[:max_chars], True, len(text)


def _git_root(cwd: Path) -> Path:
    completed = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise ValueError(f"not a git repository: {stderr or cwd}")
    return Path((completed.stdout or "").strip()).resolve()


def _git_status_result(cwd: str | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)

    branch_cp = _run_git(["branch", "--show-current"], cwd=resolved_cwd)
    branch = (branch_cp.stdout or "").strip() if branch_cp.returncode == 0 else ""

    porcelain_cp = _run_git(["status", "--short", "--branch"], cwd=resolved_cwd)
    if porcelain_cp.returncode != 0:
        raise ValueError((porcelain_cp.stderr or "git status failed").strip())

    lines = [line for line in (porcelain_cp.stdout or "").splitlines() if line.strip()]
    branch_header = lines[0] if lines and lines[0].startswith("## ") else ""
    file_lines = lines[1:] if branch_header else lines

    staged: list[dict[str, Any]] = []
    unstaged: list[dict[str, Any]] = []
    untracked: list[str] = []

    for line in file_lines:
        if line.startswith("?? "):
            untracked.append(line[3:])
            continue
        if len(line) < 3:
            continue
        x = line[0]
        y = line[1]
        path_text = line[3:]
        if x != " ":
            staged.append({"path": path_text, "code": x})
        if y != " ":
            unstaged.append({"path": path_text, "code": y})

    ahead = behind = 0
    clean = not staged and not unstaged and not untracked
    if "..." in branch_header and "[" in branch_header and "]" in branch_header:
        bracket = branch_header.split("[", 1)[1].rsplit("]", 1)[0]
        for item in [part.strip() for part in bracket.split(",")]:
            if item.startswith("ahead "):
                try:
                    ahead = int(item.split()[1])
                except Exception:
                    ahead = 0
            elif item.startswith("behind "):
                try:
                    behind = int(item.split()[1])
                except Exception:
                    behind = 0

    return {
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "branch": branch or None,
        "ahead": ahead,
        "behind": behind,
        "clean": clean,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "staged_count": len(staged),
        "unstaged_count": len(unstaged),
        "untracked_count": len(untracked),
        "status_summary": "clean working tree" if clean else "working tree has local changes",
    }


def _git_diff_result(cwd: str | None = None, path: str | None = None, staged: bool = False, max_chars: int | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else DEFAULT_MAX_DIFF_CHARS

    args = ["diff"]
    if staged:
        args.append("--cached")
    if path and str(path).strip():
        args.extend(["--", str(path)])

    completed = _run_git(args, cwd=resolved_cwd)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or "git diff failed").strip())

    diff_text, truncated, original_chars = _truncate(completed.stdout or "", limit)
    return {
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "path": path,
        "staged": bool(staged),
        "diff": diff_text,
        "truncated": truncated,
        "original_chars": original_chars,
        "max_chars": limit,
        "has_diff": bool((completed.stdout or "").strip()),
        "diff_summary": "diff available" if (completed.stdout or "").strip() else "no diff",
    }


def _git_log_result(cwd: str | None = None, path: str | None = None, limit: int | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    resolved_limit = limit if isinstance(limit, int) and limit > 0 else 10

    format_string = "%H%x1f%h%x1f%an%x1f%ad%x1f%s"
    args = ["log", f"-n{resolved_limit}", f"--pretty=format:{format_string}", "--date=iso-strict"]
    if path and str(path).strip():
        args.extend(["--", str(path)])

    completed = _run_git(args, cwd=resolved_cwd)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or "git log failed").strip())

    commits: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        commit_hash, short_hash, author, authored_at, subject = parts
        commits.append(
            {
                "commit": commit_hash,
                "short_commit": short_hash,
                "author": author,
                "authored_at": authored_at,
                "subject": subject,
            }
        )

    return {
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "path": path,
        "limit": resolved_limit,
        "commits": commits,
        "commit_count": len(commits),
    }


def _git_show_result(rev: str, cwd: str | None = None, path: str | None = None, max_chars: int | None = None) -> dict[str, Any]:
    if not isinstance(rev, str) or not rev.strip():
        raise ValueError("rev must be a non-empty string")
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else DEFAULT_MAX_DIFF_CHARS

    args = ["show", rev]
    if path and str(path).strip():
        args.extend(["--", str(path)])

    completed = _run_git(args, cwd=resolved_cwd)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or "git show failed").strip())

    text, truncated, original_chars = _truncate(completed.stdout or "", limit)
    return {
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "rev": rev,
        "path": path,
        "output": text,
        "truncated": truncated,
        "original_chars": original_chars,
        "max_chars": limit,
    }


def _git_changed_files_result(cwd: str | None = None) -> dict[str, Any]:
    status = _git_status_result(cwd=cwd)
    return {
        "git_root": status["git_root"],
        "cwd": status["cwd"],
        "branch": status["branch"],
        "staged_files": [entry["path"] for entry in status["staged"]],
        "unstaged_files": [entry["path"] for entry in status["unstaged"]],
        "untracked_files": list(status["untracked"]),
        "staged_count": status["staged_count"],
        "unstaged_count": status["unstaged_count"],
        "untracked_count": status["untracked_count"],
        "total_changed_files": len({*([entry["path"] for entry in status["staged"]]), *([entry["path"] for entry in status["unstaged"]]), *(status["untracked"])}),
    }


def _normalize_paths_input(paths: Any) -> list[str]:
    if isinstance(paths, str) and paths.strip():
        return [paths]
    if isinstance(paths, list):
        normalized = [item for item in paths if isinstance(item, str) and item.strip()]
        if normalized:
            return normalized
    raise ValueError("paths must be a non-empty string or a non-empty list of strings")


def _git_add_result(paths: Any, cwd: str | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    normalized_paths = _normalize_paths_input(paths)

    completed = _run_git(["add", "--", *normalized_paths], cwd=resolved_cwd)
    if completed.returncode != 0:
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "paths": normalized_paths,
            "failure_layer": "tool_semantic",
            "failure_kind": "git_add_failed",
            "stderr": (completed.stderr or "").strip(),
        }

    return {
        "ok": True,
        "mutation_kind": "git_add",
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "paths": normalized_paths,
        "staged_path_count": len(normalized_paths),
        "change_summary": f"staged {len(normalized_paths)} path(s)",
    }


def _git_restore_result(paths: Any, cwd: str | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    normalized_paths = _normalize_paths_input(paths)

    completed = _run_git(["restore", "--worktree", "--source=HEAD", "--", *normalized_paths], cwd=resolved_cwd)
    if completed.returncode != 0:
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "paths": normalized_paths,
            "failure_layer": "tool_semantic",
            "failure_kind": "git_restore_failed",
            "stderr": (completed.stderr or "").strip(),
        }

    return {
        "ok": True,
        "mutation_kind": "git_restore",
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "paths": normalized_paths,
        "restored_path_count": len(normalized_paths),
        "change_summary": f"restored {len(normalized_paths)} path(s) from HEAD",
    }


def _git_unstage_result(paths: Any, cwd: str | None = None) -> dict[str, Any]:
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)
    normalized_paths = _normalize_paths_input(paths)

    completed = _run_git(["restore", "--staged", "--", *normalized_paths], cwd=resolved_cwd)
    if completed.returncode != 0:
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "paths": normalized_paths,
            "failure_layer": "tool_semantic",
            "failure_kind": "git_unstage_failed",
            "stderr": (completed.stderr or completed.stdout or "").strip(),
        }

    return {
        "ok": True,
        "mutation_kind": "git_unstage",
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "paths": normalized_paths,
        "unstaged_path_count": len(normalized_paths),
        "change_summary": f"unstaged {len(normalized_paths)} path(s)",
    }


def _git_commit_result(message: str, cwd: str | None = None) -> dict[str, Any]:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)

    completed = _run_git(["commit", "-m", message], cwd=resolved_cwd)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "message": message,
            "failure_layer": "tool_semantic",
            "failure_kind": "git_commit_failed",
            "stderr": stderr,
        }

    head = _run_git(["rev-parse", "HEAD"], cwd=resolved_cwd)
    show = _run_git(["show", "--stat", "--oneline", "--format=%H%x1f%h%x1f%s", "HEAD"], cwd=resolved_cwd)
    commit_hash = (head.stdout or "").strip() if head.returncode == 0 else None
    short_commit = None
    subject = message
    changed_files_summary = ""
    if show.returncode == 0:
        lines = (show.stdout or "").splitlines()
        if lines:
            header = lines[0].split("\x1f")
            if len(header) == 3:
                commit_hash = header[0]
                short_commit = header[1]
                subject = header[2]
            changed_files_summary = "\n".join(lines[1:]).strip()

    return {
        "ok": True,
        "mutation_kind": "git_commit",
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "message": message,
        "commit": commit_hash,
        "short_commit": short_commit,
        "subject": subject,
        "changed_files_summary": changed_files_summary,
        "change_summary": f"created commit {short_commit or commit_hash or 'HEAD'}",
    }


def _git_checkout_branch_result(branch: str, cwd: str | None = None) -> dict[str, Any]:
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("branch must be a non-empty string")
    resolved_cwd = _resolve_cwd(cwd)
    git_root = _git_root(resolved_cwd)

    verify = _run_git(["rev-parse", "--verify", branch], cwd=resolved_cwd)
    if verify.returncode != 0:
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "branch": branch,
            "failure_layer": "tool_semantic",
            "failure_kind": "branch_not_found",
            "stderr": (verify.stderr or verify.stdout or "").strip(),
        }

    completed = _run_git(["checkout", branch], cwd=resolved_cwd)
    if completed.returncode != 0:
        return {
            "ok": False,
            "git_root": str(git_root),
            "cwd": str(resolved_cwd),
            "branch": branch,
            "failure_layer": "tool_semantic",
            "failure_kind": "git_checkout_branch_failed",
            "stderr": (completed.stderr or completed.stdout or "").strip(),
        }

    current = _run_git(["branch", "--show-current"], cwd=resolved_cwd)
    current_branch = (current.stdout or "").strip() if current.returncode == 0 else branch
    return {
        "ok": True,
        "mutation_kind": "git_checkout_branch",
        "git_root": str(git_root),
        "cwd": str(resolved_cwd),
        "branch": current_branch,
        "change_summary": f"checked out branch {current_branch}",
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="git_status",
            description="Return structured git working-tree status for the current workspace or an optional workspace-relative cwd.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_diff",
            description="Return bounded git diff text plus metadata for the current workspace or an optional workspace-relative cwd.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                    "path": {"type": "string", "description": "Optional path filter passed to git diff."},
                    "staged": {"type": "boolean", "description": "When true, inspect staged changes via git diff --cached."},
                    "max_chars": {"type": "integer", "description": "Optional maximum diff characters to return."},
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_log",
            description="Return structured recent commit summaries for the current workspace or an optional workspace-relative cwd.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                    "path": {"type": "string", "description": "Optional path filter passed to git log."},
                    "limit": {"type": "integer", "description": "Maximum number of commits to return."},
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_changed_files",
            description="Return the current staged, unstaged, and untracked file sets without full diff content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_show",
            description="Return bounded git show output for a revision, optionally filtered to one path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rev": {"type": "string", "description": "Revision specifier, for example HEAD or HEAD~1."},
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."},
                    "path": {"type": "string", "description": "Optional path filter passed to git show."},
                    "max_chars": {"type": "integer", "description": "Optional maximum output characters to return."},
                },
                "required": ["rev"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_add",
            description="Stage one or more paths in the current git repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}, "minItems": 1}
                        ],
                        "description": "One path or a list of paths to stage."
                    },
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "required": ["paths"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_restore",
            description="Restore one or more paths in the working tree from HEAD.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}, "minItems": 1}
                        ],
                        "description": "One path or a list of paths to restore from HEAD."
                    },
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "required": ["paths"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_unstage",
            description="Remove one or more paths from the index while keeping worktree changes intact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}, "minItems": 1}
                        ],
                        "description": "One path or a list of paths to unstage."
                    },
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "required": ["paths"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_commit",
            description="Create a git commit from the current staged changes using an explicit message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Explicit commit message."},
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="git_checkout_branch",
            description="Switch to an existing local branch in the current git repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Existing branch name to check out."},
                    "cwd": {"type": "string", "description": "Optional workspace-relative directory inside a git repository."}
                },
                "required": ["branch"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name == "git_status":
        result = _git_status_result(cwd=arguments.get("cwd"))
        text = result.get("status_summary") or ""
    elif name == "git_diff":
        result = _git_diff_result(
            cwd=arguments.get("cwd"),
            path=arguments.get("path"),
            staged=bool(arguments.get("staged", False)),
            max_chars=arguments.get("max_chars"),
        )
        text = result.get("diff") or result.get("diff_summary") or ""
    elif name == "git_log":
        result = _git_log_result(
            cwd=arguments.get("cwd"),
            path=arguments.get("path"),
            limit=arguments.get("limit"),
        )
        text = "\n".join(
            f"{item['short_commit']} {item['subject']}" for item in result.get("commits", [])
        )
    elif name == "git_changed_files":
        result = _git_changed_files_result(cwd=arguments.get("cwd"))
        text = f"changed files: staged={result.get('staged_count', 0)} unstaged={result.get('unstaged_count', 0)} untracked={result.get('untracked_count', 0)}"
    elif name == "git_show":
        result = _git_show_result(
            rev=arguments.get("rev"),
            cwd=arguments.get("cwd"),
            path=arguments.get("path"),
            max_chars=arguments.get("max_chars"),
        )
        text = result.get("output") or ""
    elif name == "git_add":
        result = _git_add_result(paths=arguments.get("paths"), cwd=arguments.get("cwd"))
        text = result.get("change_summary") or result.get("stderr") or ""
    elif name == "git_restore":
        result = _git_restore_result(paths=arguments.get("paths"), cwd=arguments.get("cwd"))
        text = result.get("change_summary") or result.get("stderr") or ""
    elif name == "git_unstage":
        result = _git_unstage_result(paths=arguments.get("paths"), cwd=arguments.get("cwd"))
        text = result.get("change_summary") or result.get("stderr") or ""
    elif name == "git_commit":
        result = _git_commit_result(message=arguments.get("message"), cwd=arguments.get("cwd"))
        text = result.get("change_summary") or result.get("stderr") or ""
    elif name == "git_checkout_branch":
        result = _git_checkout_branch_result(branch=arguments.get("branch"), cwd=arguments.get("cwd"))
        text = result.get("change_summary") or result.get("stderr") or ""
    else:
        raise ValueError(f"unknown tool: {name}")

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=result,
        isError=False,
    )


async def main() -> None:
    _workspace_root()
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
