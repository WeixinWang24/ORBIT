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
MAX_DIRECTORY_ENTRIES_ENV = "ORBIT_MCP_MAX_DIRECTORY_ENTRIES"
MAX_TREE_DEPTH_ENV = "ORBIT_MCP_MAX_TREE_DEPTH"
MAX_SEARCH_RESULTS_ENV = "ORBIT_MCP_MAX_SEARCH_RESULTS"
DEFAULT_MAX_READ_BYTES = 64 * 1024
DEFAULT_MAX_DIRECTORY_ENTRIES = 200
DEFAULT_MAX_TREE_DEPTH = 3
DEFAULT_MAX_SEARCH_RESULTS = 20

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


def _max_directory_entries() -> int:
    raw = os.environ.get(MAX_DIRECTORY_ENTRIES_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_DIRECTORY_ENTRIES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer for {MAX_DIRECTORY_ENTRIES_ENV}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_DIRECTORY_ENTRIES_ENV} must be > 0")
    return value


def _max_tree_depth() -> int:
    raw = os.environ.get(MAX_TREE_DEPTH_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_TREE_DEPTH
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer for {MAX_TREE_DEPTH_ENV}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_TREE_DEPTH_ENV} must be > 0")
    return value


def _resolve_safe_path(path: str) -> Path:
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
        raise ValueError("path not found")
    return target


def _max_search_results() -> int:
    raw = os.environ.get(MAX_SEARCH_RESULTS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_SEARCH_RESULTS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer for {MAX_SEARCH_RESULTS_ENV}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_SEARCH_RESULTS_ENV} must be > 0")
    return value


def _resolve_safe_file_path(path: str) -> Path:
    target = _resolve_safe_path(path)
    if not target.is_file():
        raise ValueError("path is not a file")
    return target


def _read_file_result(path: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    max_read_bytes = _max_read_bytes()
    raw = target.read_bytes()
    stat = target.stat()
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
        "size_bytes": stat.st_size,
        "modified_at_epoch": stat.st_mtime,
    }


def _list_directory_result(path: str) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    workspace_root = _workspace_root()
    max_entries = _max_directory_entries()
    entries = []
    children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    truncated = len(children) > max_entries
    for item in children[:max_entries]:
        kind = "directory" if item.is_dir() else "file" if item.is_file() else "other"
        entries.append(
            {
                "name": item.name,
                "path": str(item.relative_to(workspace_root)),
                "kind": kind,
            }
        )
    return {
        "path": path,
        "entries": entries,
        "truncated": truncated,
        "entry_count": len(entries),
    }


def _entry_metadata(item: Path, *, workspace_root: Path) -> dict[str, Any]:
    kind = "directory" if item.is_dir() else "file" if item.is_file() else "other"
    try:
        stat = item.stat()
        size_bytes = stat.st_size if kind == "file" else None
        modified_at = stat.st_mtime
        created_at = getattr(stat, "st_ctime", None)
        accessed_at = getattr(stat, "st_atime", None)
        permissions_octal = oct(stat.st_mode & 0o777)
    except OSError:
        size_bytes = None
        modified_at = None
        created_at = None
        accessed_at = None
        permissions_octal = None
    return {
        "name": item.name,
        "path": str(item.relative_to(workspace_root)),
        "kind": kind,
        "size_bytes": size_bytes,
        "modified_at_epoch": modified_at,
        "created_at_epoch": created_at,
        "accessed_at_epoch": accessed_at,
        "permissions_octal": permissions_octal,
    }


def _list_directory_with_sizes_result(path: str, sort_by: str = "name") -> dict[str, Any]:
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    workspace_root = _workspace_root()
    max_entries = _max_directory_entries()
    children = list(target.iterdir())
    detailed_entries = [_entry_metadata(item, workspace_root=workspace_root) for item in children]
    if sort_by == "size":
        detailed_entries.sort(key=lambda entry: (entry["size_bytes"] is None, -(entry["size_bytes"] or 0), entry["name"].lower()))
    else:
        detailed_entries.sort(key=lambda entry: (entry["kind"] != "directory", entry["name"].lower()))
    truncated = len(detailed_entries) > max_entries
    visible_entries = detailed_entries[:max_entries]
    file_entries = [entry for entry in detailed_entries if entry["kind"] == "file"]
    directory_entries = [entry for entry in detailed_entries if entry["kind"] == "directory"]
    combined_size = sum(entry["size_bytes"] or 0 for entry in file_entries)
    return {
        "path": path,
        "sort_by": sort_by,
        "entries": visible_entries,
        "summary": {
            "file_count": len(file_entries),
            "directory_count": len(directory_entries),
            "combined_file_size_bytes": combined_size,
        },
        "truncated": truncated,
        "entry_count": len(visible_entries),
    }


def _get_file_info_result(path: str) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    workspace_root = _workspace_root()
    return _entry_metadata(target, workspace_root=workspace_root)


def _directory_tree_result(path: str, max_depth: int | None = None) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    workspace_root = _workspace_root()
    depth_limit = max_depth if isinstance(max_depth, int) and max_depth > 0 else _max_tree_depth()
    node_limit = _max_directory_entries()
    state = {"count": 0, "truncated": False}

    def build(node: Path, depth: int) -> dict[str, Any]:
        state["count"] += 1
        entry = {
            "name": node.name,
            "path": str(node.relative_to(workspace_root)),
            "kind": "directory" if node.is_dir() else "file" if node.is_file() else "other",
        }
        if state["count"] >= node_limit:
            state["truncated"] = True
            return entry
        if node.is_dir() and depth < depth_limit:
            children = []
            for child in sorted(node.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if state["count"] >= node_limit:
                    state["truncated"] = True
                    break
                children.append(build(child, depth + 1))
            entry["children"] = children
        elif node.is_dir():
            entry["children"] = []
        return entry

    tree_children = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if state["count"] >= node_limit:
            state["truncated"] = True
            break
        tree_children.append(build(child, 1))
    return {
        "path": path,
        "max_depth": depth_limit,
        "truncated": state["truncated"],
        "node_count": state["count"],
        "tree": tree_children,
    }


def _search_files_result(path: str, query: str, max_results: int | None = None) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    workspace_root = _workspace_root()
    limit = max_results if isinstance(max_results, int) and max_results > 0 else _max_search_results()
    matches = []
    truncated = False
    for file_path in sorted(target.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                preview = line.strip()
                if len(preview) > 160:
                    preview = preview[:159].rstrip() + "…"
                matches.append(
                    {
                        "path": str(file_path.relative_to(workspace_root)),
                        "line": line_number,
                        "preview": preview,
                    }
                )
                if len(matches) >= limit:
                    truncated = True
                    return {
                        "path": path,
                        "query": query,
                        "matches": matches,
                        "truncated": truncated,
                        "match_count": len(matches),
                    }
    return {
        "path": path,
        "query": query,
        "matches": matches,
        "truncated": truncated,
        "match_count": len(matches),
    }


def _replace_in_file_result(path: str, old_text: str, new_text: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    content = target.read_text(encoding="utf-8")
    if old_text not in content:
        return {
            "mutation_kind": "replace_in_file",
            "failure_layer": "tool_semantic",
            "path": path,
            "replacement_count": 0,
        }
    updated = content.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")
    return {
        "mutation_kind": "replace_in_file",
        "path": path,
        "replacement_count": 1,
        "before_excerpt": old_text,
        "after_excerpt": new_text,
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
        ),
        types.Tool(
            name="list_directory",
            description="List files and directories inside a workspace-relative directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path, for example notes",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_directory_with_sizes",
            description="List files and directories inside a workspace-relative directory, including file sizes and a summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path, for example notes",
                    },
                    "sortBy": {
                        "type": "string",
                        "enum": ["name", "size"],
                        "description": "Sort entries by name or by file size.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_file_info",
            description="Get structured metadata for a workspace-relative file or directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file or directory path.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="directory_tree",
            description="Get a recursive directory tree with bounded depth and bounded node count for a workspace-relative directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path.",
                    },
                    "maxDepth": {
                        "type": "integer",
                        "description": "Maximum directory recursion depth.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="search_files",
            description="Search UTF-8 text files under a workspace-relative directory and return bounded structured match summaries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory path."},
                    "query": {"type": "string", "description": "Text to search for inside files."},
                    "maxResults": {"type": "integer", "description": "Maximum number of matches to return."},
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="replace_in_file",
            description="Replace one exact text occurrence inside a workspace-relative file and return structured mutation output.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_text": {"type": "string", "description": "Exact text to replace once."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    path = arguments.get("path")
    if name == "read_file":
        return _read_file_result(path)
    if name == "list_directory":
        return _list_directory_result(path)
    if name == "list_directory_with_sizes":
        return _list_directory_with_sizes_result(path, str(arguments.get("sortBy") or "name"))
    if name == "get_file_info":
        return _get_file_info_result(path)
    if name == "directory_tree":
        return _directory_tree_result(path, arguments.get("maxDepth"))
    if name == "search_files":
        return _search_files_result(path, arguments.get("query"), arguments.get("maxResults"))
    if name == "replace_in_file":
        return _replace_in_file_result(path, arguments.get("old_text"), arguments.get("new_text"))
    raise ValueError(f"unknown tool: {name}")


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
