from __future__ import annotations

import html
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import anyio

from .patching import apply_unified_patch_to_file
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

SERVER_NAME = "filesystem"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
SESSION_ID_ENV = "ORBIT_SESSION_ID"
MAX_READ_BYTES_ENV = "ORBIT_MCP_MAX_READ_BYTES"
MAX_DIRECTORY_ENTRIES_ENV = "ORBIT_MCP_MAX_DIRECTORY_ENTRIES"
MAX_TREE_DEPTH_ENV = "ORBIT_MCP_MAX_TREE_DEPTH"
MAX_SEARCH_RESULTS_ENV = "ORBIT_MCP_MAX_SEARCH_RESULTS"
MAX_GLOB_RESULTS_ENV = "ORBIT_MCP_MAX_GLOB_RESULTS"
DEFAULT_MAX_READ_BYTES = 64 * 1024
DEFAULT_MAX_DIRECTORY_ENTRIES = 200
DEFAULT_MAX_TREE_DEPTH = 3
DEFAULT_MAX_SEARCH_RESULTS = 20
DEFAULT_MAX_GLOB_RESULTS = 200
DEFAULT_GREP_HEAD_LIMIT = 250
DEFAULT_GREP_TIMEOUT_SECONDS = 20
DEFAULT_GREP_MAX_OUTPUT_CHARS = 12000
DEFAULT_WEB_FETCH_TIMEOUT_SECONDS = 20
DEFAULT_WEB_FETCH_MAX_CHARS = 12000
DEFAULT_WEB_FETCH_MAX_BYTES = 2 * 1024 * 1024

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


def _session_id() -> str:
    raw = os.environ.get(SESSION_ID_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {SESSION_ID_ENV}")
    return raw


def _todo_storage_path() -> Path:
    workspace_root = _workspace_root()
    session_id = _session_id()
    todo_dir = workspace_root / ".orbit_session_state"
    todo_dir.mkdir(parents=True, exist_ok=True)
    return todo_dir / f"todo_{session_id}.json"


def _load_todo_items() -> list[dict[str, Any]]:
    path = _todo_storage_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _save_todo_items(items: list[dict[str, Any]]) -> None:
    path = _todo_storage_path()
    path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _max_glob_results() -> int:
    raw = os.environ.get(MAX_GLOB_RESULTS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_GLOB_RESULTS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer for {MAX_GLOB_RESULTS_ENV}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_GLOB_RESULTS_ENV} must be > 0")
    return value


def _truncate_chars(text: str, limit: int = DEFAULT_GREP_MAX_OUTPUT_CHARS) -> tuple[str, bool, int]:
    if len(text) <= limit:
        return text, False, len(text)
    return text[:limit], True, len(text)


def _relativize_to_workspace(candidate: str | Path, workspace_root: Path) -> str:
    try:
        return str(Path(candidate).resolve().relative_to(workspace_root))
    except Exception:
        return str(candidate)


def _split_glob_patterns(glob_value: str | None) -> list[str]:
    if not glob_value:
        return []
    return [part for part in str(glob_value).split() if part]


def _path_matches_glob(rel_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    path_obj = Path(rel_path)
    return any(path_obj.match(pattern) for pattern in patterns)


def _python_grep_result(
    pattern: str,
    target: Path,
    workspace_root: Path,
    path_label: str,
    glob: str | None,
    output_mode: str,
    context_before: int | None,
    context_after: int | None,
    context: int | None,
    show_line_numbers: bool | None,
    case_insensitive: bool | None,
    file_type: str | None,
    head_limit: int | None,
    offset: int | None,
    multiline: bool | None,
) -> dict[str, Any]:
    flags = re.MULTILINE
    if case_insensitive:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.DOTALL
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return {
            "path": path_label,
            "pattern": pattern,
            "mode": output_mode,
            "timed_out": False,
            "failure_layer": "tool_semantic",
            "failure_kind": "invalid_pattern",
            "stderr": str(exc),
        }

    limit = DEFAULT_GREP_HEAD_LIMIT if head_limit is None else head_limit
    offset_value = offset if isinstance(offset, int) and offset >= 0 else 0
    glob_patterns = _split_glob_patterns(glob)
    allowed_suffix = f".{file_type.lstrip('.')}" if file_type else None
    candidate_files: list[Path] = []
    if target.is_file():
        candidate_files = [target]
    else:
        candidate_files = [p for p in sorted(target.rglob('*')) if p.is_file()]

    results_content: list[str] = []
    results_files: list[str] = []
    results_counts: list[str] = []
    total_matches = 0

    before = context if isinstance(context, int) and context >= 0 else (context_before or 0)
    after = context if isinstance(context, int) and context >= 0 else (context_after or 0)

    for file_path in candidate_files:
        rel_path = str(file_path.relative_to(workspace_root))
        if allowed_suffix and file_path.suffix != allowed_suffix:
            continue
        if not _path_matches_glob(rel_path, glob_patterns):
            continue
        try:
            text = file_path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue

        if multiline:
            matches = list(regex.finditer(text))
            if not matches:
                continue
            if output_mode == 'files_with_matches':
                results_files.append(rel_path)
                continue
            if output_mode == 'count':
                count_value = len(matches)
                total_matches += count_value
                results_counts.append(f"{rel_path}:{count_value}")
                continue
            lines = text.splitlines()
            line_starts = []
            position = 0
            for idx, line in enumerate(lines, start=1):
                line_starts.append((position, idx, line))
                position += len(line) + 1
            seen = set()
            for match in matches:
                line_number = 1
                matched_line = text
                for start_pos, idx, line in line_starts:
                    if start_pos <= match.start() <= start_pos + len(line):
                        line_number = idx
                        matched_line = line
                        break
                if line_number in seen:
                    continue
                seen.add(line_number)
                total_matches += 1
                prefix = f"{rel_path}:{line_number}:" if show_line_numbers is not False else f"{rel_path}:"
                results_content.append(prefix + matched_line)
            continue

        lines = text.splitlines()
        file_match_count = 0
        emitted_file = False
        for idx, line in enumerate(lines, start=1):
            if not regex.search(line):
                continue
            file_match_count += 1
            if output_mode == 'files_with_matches':
                if not emitted_file:
                    results_files.append(rel_path)
                    emitted_file = True
                continue
            if output_mode == 'count':
                continue
            start = max(1, idx - before)
            end = min(len(lines), idx + after)
            for line_idx in range(start, end + 1):
                prefix = f"{rel_path}:{line_idx}:" if show_line_numbers is not False else f"{rel_path}:"
                entry = prefix + lines[line_idx - 1]
                if entry not in results_content:
                    results_content.append(entry)
        if file_match_count:
            total_matches += file_match_count
            if output_mode == 'count':
                results_counts.append(f"{rel_path}:{file_match_count}")

    if output_mode == 'content':
        sliced = results_content[offset_value:] if limit == 0 else results_content[offset_value : offset_value + limit]
        applied_limit = None if limit == 0 or len(results_content) - offset_value <= limit else limit
        content = "\n".join(sliced)
        content_text, content_truncated, content_original = _truncate_chars(content)
        return {
            "path": path_label,
            "pattern": pattern,
            "mode": output_mode,
            "content": content_text,
            "numFiles": 0,
            "filenames": [],
            "numLines": len(sliced),
            "appliedLimit": applied_limit,
            "appliedOffset": offset_value if offset_value else None,
            "content_truncated": content_truncated,
            "content_original_chars": content_original,
            "engine": "python_fallback",
        }

    if output_mode == 'count':
        sliced = results_counts[offset_value:] if limit == 0 else results_counts[offset_value : offset_value + limit]
        applied_limit = None if limit == 0 or len(results_counts) - offset_value <= limit else limit
        content = "\n".join(sliced)
        content_text, content_truncated, content_original = _truncate_chars(content)
        return {
            "path": path_label,
            "pattern": pattern,
            "mode": output_mode,
            "content": content_text,
            "numFiles": len(sliced),
            "filenames": [],
            "numMatches": total_matches,
            "appliedLimit": applied_limit,
            "appliedOffset": offset_value if offset_value else None,
            "content_truncated": content_truncated,
            "content_original_chars": content_original,
            "engine": "python_fallback",
        }

    sliced = results_files[offset_value:] if limit == 0 else results_files[offset_value : offset_value + limit]
    applied_limit = None if limit == 0 or len(results_files) - offset_value <= limit else limit
    return {
        "path": path_label,
        "pattern": pattern,
        "mode": output_mode,
        "numFiles": len(sliced),
        "filenames": sliced,
        "appliedLimit": applied_limit,
        "appliedOffset": offset_value if offset_value else None,
        "engine": "python_fallback",
    }


def _grep_result(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    output_mode: str | None = None,
    context_before: int | None = None,
    context_after: int | None = None,
    context: int | None = None,
    show_line_numbers: bool | None = None,
    case_insensitive: bool | None = None,
    file_type: str | None = None,
    head_limit: int | None = None,
    offset: int | None = None,
    multiline: bool | None = None,
) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    mode = output_mode if output_mode in {"content", "files_with_matches", "count"} else "files_with_matches"
    limit = DEFAULT_GREP_HEAD_LIMIT if head_limit is None else head_limit
    if limit < 0:
        raise ValueError("head_limit must be >= 0")
    offset_value = offset if isinstance(offset, int) and offset >= 0 else 0
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")

    workspace_root = _workspace_root()
    rg_path = shutil.which("rg")
    if rg_path is None:
        return _python_grep_result(
            pattern=pattern,
            target=target,
            workspace_root=workspace_root,
            path_label=path,
            glob=glob,
            output_mode=mode,
            context_before=context_before,
            context_after=context_after,
            context=context,
            show_line_numbers=show_line_numbers,
            case_insensitive=case_insensitive,
            file_type=file_type,
            head_limit=head_limit,
            offset=offset,
            multiline=multiline,
        )
    args: list[str] = ["--hidden", "--max-columns", "500"]
    if multiline:
        args.extend(["-U", "--multiline-dotall"])
    if case_insensitive:
        args.append("-i")
    if mode == "files_with_matches":
        args.append("-l")
    elif mode == "count":
        args.append("-c")
    elif show_line_numbers is not False:
        args.append("-n")

    if mode == "content":
        args.extend(["--with-filename", "--no-heading"])

    if mode == "content":
        if isinstance(context, int) and context >= 0:
            args.extend(["-C", str(context)])
        else:
            if isinstance(context_before, int) and context_before >= 0:
                args.extend(["-B", str(context_before)])
            if isinstance(context_after, int) and context_after >= 0:
                args.extend(["-A", str(context_after)])

    if pattern.startswith("-"):
        args.extend(["-e", pattern])
    else:
        args.append(pattern)

    if file_type:
        args.extend(["--type", file_type])
    if glob:
        for glob_pattern in [part for part in str(glob).split() if part]:
            args.extend(["--glob", glob_pattern])

    command = [rg_path, *args, str(target)]
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=DEFAULT_GREP_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout_text, stdout_truncated, stdout_original = _truncate_chars(exc.stdout or "")
        stderr_text, stderr_truncated, stderr_original = _truncate_chars(exc.stderr or "")
        return {
            "path": path,
            "pattern": pattern,
            "mode": mode,
            "timed_out": True,
            "failure_layer": "runtime_execution",
            "failure_kind": "timeout",
            "stdout": stdout_text,
            "stderr": stderr_text,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "stdout_original_chars": stdout_original,
            "stderr_original_chars": stderr_original,
        }

    if completed.returncode not in {0, 1}:
        stdout_text, stdout_truncated, stdout_original = _truncate_chars(completed.stdout or "")
        stderr_text, stderr_truncated, stderr_original = _truncate_chars(completed.stderr or "")
        return {
            "path": path,
            "pattern": pattern,
            "mode": mode,
            "timed_out": False,
            "failure_layer": "tool_semantic",
            "failure_kind": "nonzero_exit",
            "exit_code": completed.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "stdout_original_chars": stdout_original,
            "stderr_original_chars": stderr_original,
        }

    lines = [line for line in (completed.stdout or "").splitlines() if line]
    lines.sort()
    sliced = lines[offset_value:] if limit == 0 else lines[offset_value : offset_value + limit]
    applied_limit = None if limit == 0 or len(lines) - offset_value <= limit else limit

    if mode == "content":
        relativized = []
        for line in sliced:
            colon_index = line.find(":")
            hyphen_index = line.find("-")
            split_index = -1
            if colon_index > 0 and hyphen_index > 0:
                split_index = min(colon_index, hyphen_index)
            elif colon_index > 0:
                split_index = colon_index
            elif hyphen_index > 0:
                split_index = hyphen_index
            if split_index > 0:
                file_path = line[:split_index]
                rest = line[split_index:]
                rel = _relativize_to_workspace(file_path, workspace_root)
                normalized_rest = rest
                if normalized_rest.startswith("-"):
                    normalized_rest = ":" + normalized_rest[1:].replace("-", ":", 1)
                relativized.append(rel + normalized_rest)
            else:
                relativized.append(line)
        content = "\n".join(relativized)
        content_text, content_truncated, content_original = _truncate_chars(content)
        return {
            "path": path,
            "pattern": pattern,
            "mode": mode,
            "content": content_text,
            "numFiles": 0,
            "filenames": [],
            "numLines": len(relativized),
            "appliedLimit": applied_limit,
            "appliedOffset": offset_value if offset_value else None,
            "content_truncated": content_truncated,
            "content_original_chars": content_original,
        }

    if mode == "count":
        relativized = []
        total_matches = 0
        file_count = 0
        for line in sliced:
            colon_index = line.rfind(":")
            if colon_index > 0:
                file_path = line[:colon_index]
                count_part = line[colon_index:]
                rel = _relativize_to_workspace(file_path, workspace_root)
                relativized.append(rel + count_part)
                try:
                    total_matches += int(count_part[1:])
                    file_count += 1
                except Exception:
                    pass
            else:
                relativized.append(line)
        content = "\n".join(relativized)
        content_text, content_truncated, content_original = _truncate_chars(content)
        return {
            "path": path,
            "pattern": pattern,
            "mode": mode,
            "content": content_text,
            "numFiles": file_count,
            "filenames": [],
            "numMatches": total_matches,
            "appliedLimit": applied_limit,
            "appliedOffset": offset_value if offset_value else None,
            "content_truncated": content_truncated,
            "content_original_chars": content_original,
        }

    filenames = []
    for line in sliced:
        filenames.append(_relativize_to_workspace(line, workspace_root))
    return {
        "path": path,
        "pattern": pattern,
        "mode": mode,
        "numFiles": len(filenames),
        "filenames": filenames,
        "appliedLimit": applied_limit,
        "appliedOffset": offset_value if offset_value else None,
    }


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


def _search_files_result(path: str, query: str, max_results: int | None = None, offset: int | None = None) -> dict[str, Any]:
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    workspace_root = _workspace_root()
    limit = max_results if isinstance(max_results, int) and max_results > 0 else _max_search_results()
    offset_value = offset if isinstance(offset, int) and offset >= 0 else 0
    all_matches = []
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
                all_matches.append(
                    {
                        "path": str(file_path.relative_to(workspace_root)),
                        "line": line_number,
                        "preview": preview,
                    }
                )
    visible_matches = all_matches[offset_value : offset_value + limit]
    truncated = len(all_matches) > offset_value + limit
    return {
        "path": path,
        "query": query,
        "offset": offset_value,
        "matches": visible_matches,
        "truncated": truncated,
        "match_count": len(visible_matches),
    }


def _glob_result(base_path: str = ".", pattern: str | None = None, max_results: int | None = None, offset: int | None = None) -> dict[str, Any]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")
    target = _resolve_safe_path(base_path)
    if not target.is_dir():
        raise ValueError("base_path is not a directory")
    workspace_root = _workspace_root()
    limit = max_results if isinstance(max_results, int) and max_results > 0 else _max_glob_results()
    offset_value = offset if isinstance(offset, int) and offset >= 0 else 0
    all_matches = []
    for item in sorted(target.glob(pattern), key=lambda p: str(p.relative_to(workspace_root)).lower()):
        kind = "directory" if item.is_dir() else "file" if item.is_file() else "other"
        all_matches.append(
            {
                "path": str(item.relative_to(workspace_root)),
                "kind": kind,
                "name": item.name,
            }
        )
    visible_matches = all_matches[offset_value : offset_value + limit]
    truncated = len(all_matches) > offset_value + limit
    return {
        "base_path": base_path,
        "path": base_path,
        "pattern": pattern,
        "offset": offset_value,
        "matches": visible_matches,
        "truncated": truncated,
        "match_count": len(visible_matches),
    }


def _todo_write_result(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    normalized = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError("each todo item must be an object")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("each todo item requires non-empty content")
        status = item.get("status") if isinstance(item.get("status"), str) and item.get("status") else "pending"
        normalized.append(
            {
                "id": str(item.get("id") or f"todo-{idx}"),
                "content": content,
                "status": status,
                "priority": item.get("priority"),
            }
        )
    _save_todo_items(normalized)
    counts: dict[str, int] = {}
    for item in normalized:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "items": normalized,
        "item_count": len(normalized),
        "status_counts": counts,
        "current_focus": next((item for item in normalized if item.get("status") not in {"done", "completed", "cancelled"}), None),
    }


def _todo_read_result() -> dict[str, Any]:
    items = _load_todo_items()
    counts: dict[str, int] = {}
    for item in items:
        status = item.get("status") if isinstance(item, dict) else None
        if isinstance(status, str) and status:
            counts[status] = counts.get(status, 0) + 1
    return {
        "items": items,
        "item_count": len(items),
        "status_counts": counts,
        "current_focus": next((item for item in items if isinstance(item, dict) and item.get("status") not in {"done", "completed", "cancelled"}), None),
    }


def _html_to_text(raw_html: str, *, extract_main_text: bool = True) -> tuple[str | None, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else None
    content = raw_html
    if extract_main_text:
        main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, flags=re.IGNORECASE | re.DOTALL)
        article_match = re.search(r"<article[^>]*>(.*?)</article>", raw_html, flags=re.IGNORECASE | re.DOTALL)
        if main_match:
            content = main_match.group(1)
        elif article_match:
            content = article_match.group(1)
        else:
            body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, flags=re.IGNORECASE | re.DOTALL)
            if body_match:
                content = body_match.group(1)
    content = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", content, flags=re.IGNORECASE)
    content = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", content, flags=re.IGNORECASE)
    content = re.sub(r"<[^>]+>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return title, content


def _is_tls_cert_verify_failure(exc: Exception) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError):
            return True
        if isinstance(reason, Exception) and "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return True
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)


def _web_fetch_result(
    url: str,
    max_chars: int | None = None,
    format_hint: str | None = None,
    extract_main_text: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("url must not include credentials")
    if not parsed.netloc:
        raise ValueError("url must include a hostname")

    limit_chars = max_chars if isinstance(max_chars, int) and max_chars > 0 else DEFAULT_WEB_FETCH_MAX_CHARS
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ORBIT-WebFetch/0.1",
            "Accept": "text/html, text/plain, application/json, text/markdown, */*",
        },
        method="GET",
    )
    tls_verification_bypassed = False
    try:
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_WEB_FETCH_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type", "")
                final_url = response.geturl()
                charset = response.headers.get_content_charset() or "utf-8"
                raw_bytes = response.read(DEFAULT_WEB_FETCH_MAX_BYTES + 1)
        except Exception as fetch_exc:
            if not _is_tls_cert_verify_failure(fetch_exc):
                raise
            insecure_context = ssl.create_default_context()
            insecure_context.check_hostname = False
            insecure_context.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(request, timeout=DEFAULT_WEB_FETCH_TIMEOUT_SECONDS, context=insecure_context) as response:
                tls_verification_bypassed = True
                status = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type", "")
                final_url = response.geturl()
                charset = response.headers.get_content_charset() or "utf-8"
                raw_bytes = response.read(DEFAULT_WEB_FETCH_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(DEFAULT_WEB_FETCH_MAX_BYTES + 1) if hasattr(exc, "read") else b""
        text = body.decode("utf-8", errors="replace")
        content, truncated, original_chars = _truncate_chars(text, limit_chars)
        return {
            "url": url,
            "final_url": getattr(exc, "url", url),
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if getattr(exc, "headers", None) else "",
            "title": None,
            "content": content,
            "truncated": truncated,
            "content_original_chars": original_chars,
            "failure_layer": "tool_semantic",
            "failure_kind": "http_error",
        }
    except Exception as exc:
        return {
            "url": url,
            "final_url": url,
            "status": None,
            "content_type": "",
            "title": None,
            "content": str(exc),
            "truncated": False,
            "content_original_chars": len(str(exc)),
            "failure_layer": "runtime_execution",
            "failure_kind": "fetch_error",
        }

    over_byte_limit = len(raw_bytes) > DEFAULT_WEB_FETCH_MAX_BYTES
    if over_byte_limit:
        raw_bytes = raw_bytes[:DEFAULT_WEB_FETCH_MAX_BYTES]
    raw_text = raw_bytes.decode(charset, errors="replace")
    hint = (format_hint or "").strip().lower()
    is_html = "html" in content_type.lower() or hint == "html"
    if is_html:
        title, normalized = _html_to_text(raw_text, extract_main_text=extract_main_text is not False)
    else:
        title = None
        normalized = raw_text.strip()
    content, truncated, original_chars = _truncate_chars(normalized, limit_chars)
    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "title": title,
        "content": content,
        "truncated": truncated or over_byte_limit,
        "content_original_chars": original_chars,
        "tls_verification_bypassed": tls_verification_bypassed,
    }


def _write_file_result(path: str, content: str) -> dict[str, Any]:
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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "mutation_kind": "write_file",
        "path": path,
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


def _replace_all_in_file_result(path: str, old_text: str, new_text: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    content = target.read_text(encoding="utf-8")
    replacement_count = content.count(old_text)
    if replacement_count == 0:
        return {
            "mutation_kind": "replace_all_in_file",
            "failure_layer": "tool_semantic",
            "path": path,
            "replacement_count": 0,
        }
    updated = content.replace(old_text, new_text)
    target.write_text(updated, encoding="utf-8")
    return {
        "mutation_kind": "replace_all_in_file",
        "path": path,
        "replacement_count": replacement_count,
        "before_excerpt": old_text,
        "after_excerpt": new_text,
    }


def _replace_block_in_file_result(path: str, old_block: str, new_block: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    content = target.read_text(encoding="utf-8")
    match_count = content.count(old_block)
    if match_count == 0:
        return {
            "mutation_kind": "replace_block_in_file",
            "failure_layer": "tool_semantic",
            "path": path,
            "match_count": 0,
            "replacement_count": 0,
        }
    if match_count > 1:
        return {
            "mutation_kind": "replace_block_in_file",
            "failure_layer": "tool_semantic",
            "path": path,
            "match_count": match_count,
            "replacement_count": 0,
        }
    updated = content.replace(old_block, new_block, 1)
    target.write_text(updated, encoding="utf-8")
    return {
        "mutation_kind": "replace_block_in_file",
        "path": path,
        "match_count": 1,
        "replacement_count": 1,
        "before_excerpt": old_block,
        "after_excerpt": new_block,
    }


def _apply_exact_hunk_result(path: str, before_context: str, old_block: str, after_context: str, new_block: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    content = target.read_text(encoding="utf-8")
    old_hunk = before_context + old_block + after_context
    new_hunk = before_context + new_block + after_context
    match_count = content.count(old_hunk)
    if match_count == 0:
        return {
            "mutation_kind": "apply_exact_hunk",
            "failure_layer": "tool_semantic",
            "path": path,
            "match_count": 0,
            "replacement_count": 0,
            "change_summary": "0 exact hunk matches",
        }
    if match_count > 1:
        return {
            "mutation_kind": "apply_exact_hunk",
            "failure_layer": "tool_semantic",
            "path": path,
            "match_count": match_count,
            "replacement_count": 0,
            "change_summary": f"{match_count} exact hunk matches",
        }
    updated = content.replace(old_hunk, new_hunk, 1)
    target.write_text(updated, encoding="utf-8")
    return {
        "mutation_kind": "apply_exact_hunk",
        "path": path,
        "match_count": 1,
        "replacement_count": 1,
        "before_excerpt": old_block,
        "after_excerpt": new_block,
        "change_summary": "1 exact hunk applied",
    }


def _apply_unified_patch_result(path: str, patch: str) -> dict[str, Any]:
    result = apply_unified_patch_to_file(
        workspace_root=_workspace_root(),
        path=path,
        patch=patch,
    )
    if not result.get("ok"):
        return {
            "mutation_kind": "apply_unified_patch",
            "path": path,
            "failure_layer": result.get("failure_layer", "tool_semantic"),
            "failure_kind": result.get("failure_kind", "patch_apply_failed"),
            "change_summary": result.get("change_summary"),
            "applied_hunk_count": result.get("applied_hunk_count", 0),
            **({"failed_hunk": result.get("failed_hunk")} if result.get("failed_hunk") is not None else {}),
        }
    return result


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
                    "offset": {"type": "integer", "description": "Skip the first N matches before returning the bounded result page."},
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="glob",
            description="Match workspace-relative filesystem entries under a base directory using a bounded glob pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern relative to the base directory, for example **/*.py or src/*.md."},
                    "path": {"type": "string", "description": "Workspace-relative base directory path. Preferred alias for the glob root. Defaults to the workspace root."},
                    "base_path": {"type": "string", "description": "Workspace-relative base directory path. Legacy-compatible alias for path."},
                    "maxResults": {"type": "integer", "description": "Maximum number of matches to return."},
                    "offset": {"type": "integer", "description": "Skip the first N matches before returning the bounded result page."},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="grep",
            description="Search file contents with ripgrep-style regex semantics inside a workspace-relative path and return bounded structured results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression pattern to search for in file contents."},
                    "path": {"type": "string", "description": "Workspace-relative file or directory path. Defaults to the workspace root."},
                    "glob": {"type": "string", "description": "Optional glob filter for candidate files, for example *.py or **/*.md."},
                    "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"], "description": "Result mode: matching content lines, matching files only, or per-file counts."},
                    "-B": {"type": "integer", "description": "Context lines before each match when output_mode=content."},
                    "-A": {"type": "integer", "description": "Context lines after each match when output_mode=content."},
                    "context": {"type": "integer", "description": "Context lines before and after each match when output_mode=content."},
                    "-n": {"type": "boolean", "description": "Show line numbers in content mode. Defaults to true."},
                    "-i": {"type": "boolean", "description": "Case-insensitive search."},
                    "type": {"type": "string", "description": "Optional ripgrep file type filter, for example py, js, or md."},
                    "head_limit": {"type": "integer", "description": "Maximum number of returned lines or entries. Use 0 for unlimited with care."},
                    "offset": {"type": "integer", "description": "Skip the first N results before returning the bounded page."},
                    "multiline": {"type": "boolean", "description": "Enable multiline regex mode."}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="web_fetch",
            description="Fetch remote web content from an http(s) URL and return bounded extracted text plus basic metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully qualified http(s) URL to fetch."},
                    "max_chars": {"type": "integer", "description": "Maximum number of characters to return from the normalized content."},
                    "format_hint": {"type": "string", "description": "Optional hint such as html, markdown, text, or json."},
                    "extract_main_text": {"type": "boolean", "description": "Prefer article/main/body extraction for HTML before text normalization."}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="todo_write",
            description="Replace the current session-scoped todo list with a structured list of work items.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                                "priority": {"type": ["string", "integer", "number", "null"]}
                            },
                            "required": ["content"],
                            "additionalProperties": False,
                        }
                    }
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="todo_read",
            description="Read the current session-scoped structured todo list.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="write_file",
            description="Write UTF-8 text to a workspace-relative file, creating parent directories when needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
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
        types.Tool(
            name="replace_all_in_file",
            description="Replace all exact text occurrences inside a workspace-relative file and return structured mutation output.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_text": {"type": "string", "description": "Exact text to replace everywhere."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="replace_block_in_file",
            description="Replace one exact block inside a workspace-relative file and fail when the block is absent or ambiguous.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_block": {"type": "string", "description": "Exact block that must match exactly once."},
                    "new_block": {"type": "string", "description": "Replacement block."},
                },
                "required": ["path", "old_block", "new_block"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="apply_exact_hunk",
            description="Apply one exact hunk replacement using before-context, old block, after-context, and new block, failing when the hunk is absent or ambiguous.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "before_context": {"type": "string", "description": "Exact context immediately before the old block."},
                    "old_block": {"type": "string", "description": "Exact block to replace within the hunk."},
                    "after_context": {"type": "string", "description": "Exact context immediately after the old block."},
                    "new_block": {"type": "string", "description": "Replacement block."},
                },
                "required": ["path", "before_context", "old_block", "after_context", "new_block"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="apply_unified_patch",
            description="Apply a single-file unified diff patch to a workspace-relative file using strict hunk-context matching.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "patch": {"type": "string", "description": "Single-file unified diff patch text. May include ---/+++ headers and one or more @@ hunks."},
                },
                "required": ["path", "patch"],
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
        return _search_files_result(path, arguments.get("query"), arguments.get("maxResults"), arguments.get("offset"))
    if name == "glob":
        return _glob_result(
            str(arguments.get("path") or arguments.get("base_path") or "."),
            arguments.get("pattern"),
            arguments.get("maxResults"),
            arguments.get("offset"),
        )
    if name == "grep":
        return _grep_result(
            pattern=arguments.get("pattern"),
            path=str(arguments.get("path") or "."),
            glob=arguments.get("glob"),
            output_mode=arguments.get("output_mode"),
            context_before=arguments.get("-B"),
            context_after=arguments.get("-A"),
            context=arguments.get("context"),
            show_line_numbers=arguments.get("-n"),
            case_insensitive=arguments.get("-i"),
            file_type=arguments.get("type"),
            head_limit=arguments.get("head_limit"),
            offset=arguments.get("offset"),
            multiline=arguments.get("multiline"),
        )
    if name == "web_fetch":
        return _web_fetch_result(
            arguments.get("url"),
            arguments.get("max_chars"),
            arguments.get("format_hint"),
            arguments.get("extract_main_text"),
        )
    if name == "todo_write":
        return _todo_write_result(arguments.get("items"))
    if name == "todo_read":
        return _todo_read_result()
    if name == "write_file":
        return _write_file_result(path, arguments.get("content"))
    if name == "replace_in_file":
        return _replace_in_file_result(path, arguments.get("old_text"), arguments.get("new_text"))
    if name == "replace_all_in_file":
        return _replace_all_in_file_result(path, arguments.get("old_text"), arguments.get("new_text"))
    if name == "replace_block_in_file":
        return _replace_block_in_file_result(path, arguments.get("old_block"), arguments.get("new_block"))
    if name == "apply_exact_hunk":
        return _apply_exact_hunk_result(
            path,
            arguments.get("before_context"),
            arguments.get("old_block"),
            arguments.get("after_context"),
            arguments.get("new_block"),
        )
    if name == "apply_unified_patch":
        return _apply_unified_patch_result(path, arguments.get("patch"))
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
