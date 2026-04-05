from __future__ import annotations

import ast
import json
import os
import re
import ssl
import subprocess
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from .patching import apply_unified_patch_to_file

SERVER_NAME = "filesystem"
SERVER_VERSION = "0.1.0"
WORKSPACE_ROOT_ENV = "ORBIT_WORKSPACE_ROOT"
MAX_READ_BYTES_ENV = "ORBIT_MCP_MAX_READ_BYTES"
MAX_DIRECTORY_ENTRIES_ENV = "ORBIT_MCP_MAX_DIRECTORY_ENTRIES"
MAX_TREE_DEPTH_ENV = "ORBIT_MCP_MAX_TREE_DEPTH"
MAX_SEARCH_RESULTS_ENV = "ORBIT_MCP_MAX_SEARCH_RESULTS"
SESSION_ID_ENV = "ORBIT_SESSION_ID"
DEFAULT_MAX_READ_BYTES = 64 * 1024
DEFAULT_MAX_DIRECTORY_ENTRIES = 200
DEFAULT_MAX_TREE_DEPTH = 3
DEFAULT_MAX_SEARCH_RESULTS = 20
DEFAULT_WEB_FETCH_TIMEOUT_SECONDS = 15

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


def _session_id() -> str:
    raw = os.environ.get(SESSION_ID_ENV, "").strip()
    return raw or "default"


def _todo_store_path() -> Path:
    return _workspace_root() / ".orbit_session_todos" / f"{_session_id()}.json"


def _load_todo_items() -> list[dict[str, Any]]:
    store = _todo_store_path()
    if not store.exists():
        return []
    try:
        payload = json.loads(store.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        normalized.append(
            {
                "id": str(item.get("id") or f"todo-{index}"),
                "content": content,
                "status": str(item.get("status") or "pending"),
                "priority": item.get("priority"),
            }
        )
    return normalized


def _todo_read_result() -> dict[str, Any]:
    items = _load_todo_items()
    return {
        "session_id": _session_id(),
        "item_count": len(items),
        "items": items,
    }


def _todo_write_result(items: Any) -> dict[str, Any]:
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError("each todo item must be an object")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("each todo item must include non-empty content")
        normalized.append(
            {
                "id": str(item.get("id") or f"todo-{index}"),
                "content": content,
                "status": str(item.get("status") or "pending"),
                "priority": item.get("priority"),
            }
        )
    store = _todo_store_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    payload = {"session_id": _session_id(), "items": normalized}
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "session_id": _session_id(),
        "item_count": len(normalized),
        "items": normalized,
    }


def _normalize_web_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _html_to_text(html: str, *, extract_main_text: bool) -> str:
    candidate = html
    if extract_main_text:
        main_match = re.search(r"<(main|article)\b[^>]*>(.*?)</\1>", html, flags=re.IGNORECASE | re.DOTALL)
        body_match = re.search(r"<body\b[^>]*>(.*?)</body>", html, flags=re.IGNORECASE | re.DOTALL)
        if main_match:
            candidate = main_match.group(2)
        elif body_match:
            candidate = body_match.group(1)
    candidate = re.sub(r"<script\b[^>]*>.*?</script>", " ", candidate, flags=re.IGNORECASE | re.DOTALL)
    candidate = re.sub(r"<style\b[^>]*>.*?</style>", " ", candidate, flags=re.IGNORECASE | re.DOTALL)
    candidate = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", candidate, flags=re.IGNORECASE | re.DOTALL)
    candidate = re.sub(r"</?(p|div|section|article|main|header|footer|nav|aside|li|ul|ol|h1|h2|h3|h4|h5|h6|br|tr|table)\b[^>]*>", "\n", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"<[^>]+>", " ", candidate)
    candidate = unescape(candidate)
    candidate = re.sub(r"[ \t\f\v]+", " ", candidate)
    return _normalize_web_text(candidate)


def _web_fetch_result(url: str, max_chars: int | None = None, format_hint: str | None = None, extract_main_text: bool | None = None) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else 12000
    prefer_main = bool(extract_main_text)
    request = Request(url, headers={"User-Agent": "ORBIT web_fetch/0.1"})
    try:
        with urlopen(request, timeout=DEFAULT_WEB_FETCH_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            status = getattr(response, "status", None)
            content_type = response.headers.get("Content-Type", "")
            raw_bytes = response.read(limit * 4)
    except HTTPError as exc:
        return {
            "ok": False,
            "url": url,
            "failure_layer": "transport",
            "failure_kind": "http_error",
            "status_code": exc.code,
            "message": str(exc),
        }
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        failure_kind = "ssl_verification_failed" if isinstance(reason, ssl.SSLCertVerificationError) else "network_error"
        return {
            "ok": False,
            "url": url,
            "failure_layer": "transport",
            "failure_kind": failure_kind,
            "message": str(exc),
        }

    charset_match = re.search(r"charset=([^;]+)", content_type, flags=re.IGNORECASE)
    encoding = charset_match.group(1).strip() if charset_match else "utf-8"
    try:
        raw_text = raw_bytes.decode(encoding, errors="replace")
    except LookupError:
        raw_text = raw_bytes.decode("utf-8", errors="replace")
    inferred_format = (format_hint or "").strip().lower()
    if not inferred_format:
        if "html" in content_type.lower():
            inferred_format = "html"
        elif "json" in content_type.lower():
            inferred_format = "json"
        else:
            inferred_format = "text"
    content = _html_to_text(raw_text, extract_main_text=prefer_main) if inferred_format == "html" else _normalize_web_text(raw_text)
    truncated = len(content) > limit
    bounded = content[:limit]
    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "status_code": status,
        "content_type": content_type,
        "format": inferred_format,
        "extract_main_text": prefer_main,
        "content": bounded,
        "content_chars": len(bounded),
        "truncated": truncated,
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


def _extract_python_symbols(path: str, target: Path, *, include_nodes: bool = False) -> list[dict[str, Any]]:
    if target.suffix != ".py":
        raise ValueError("Python symbol tools currently support Python files only")
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    symbols: list[dict[str, Any]] = []

    def visit_nodes(nodes: list[ast.stmt], container: str | None = None) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                symbol = {
                    "path": path,
                    "name": node.name,
                    "kind": "class",
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "container": container,
                }
                if include_nodes:
                    symbol["_node"] = node
                symbols.append(symbol)
                visit_nodes(node.body, container=node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = {
                    "path": path,
                    "name": node.name,
                    "kind": "method" if container else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"),
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "container": container,
                }
                if include_nodes:
                    symbol["_node"] = node
                symbols.append(symbol)

    visit_nodes(tree.body)
    return symbols


def _extract_ts_js_symbols(path: str, target: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if target.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        raise ValueError("TS/JS symbol tools currently support .ts, .tsx, .js, and .jsx files only")
    helper = Path(__file__).with_name("ts_js_symbols.js")
    try:
        completed = subprocess.run(
            ["node", str(helper), str(target)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError((exc.stderr or "TS/JS symbol extraction failed").strip()) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("TS/JS symbol extraction timed out") from exc
    if completed.returncode != 0:
        raise ValueError((completed.stderr or "TS/JS symbol extraction failed").strip())
    payload = json.loads(completed.stdout or "{}")
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
    references = payload.get("references") if isinstance(payload.get("references"), list) else []
    for symbol in symbols:
        if isinstance(symbol, dict):
            symbol["path"] = path
    for reference in references:
        if isinstance(reference, dict):
            reference["path"] = path
    language = {
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
    }[target.suffix]
    return language, symbols, references


def _get_symbols_overview_result(path: str) -> dict[str, Any]:
    target = _resolve_safe_file_path(path)
    if target.suffix == ".py":
        language = "python"
        symbols = _extract_python_symbols(path, target)
    else:
        language, symbols, _ = _extract_ts_js_symbols(path, target)
    return {
        "path": path,
        "language": language,
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def _iter_python_scope_candidates(path: str | None = None) -> tuple[Path, list[Path], str | None]:
    workspace_root = _workspace_root()
    target_scope = _resolve_safe_path(path) if isinstance(path, str) and path.strip() else workspace_root
    if target_scope.is_file():
        return workspace_root, [target_scope], path
    return workspace_root, sorted(target_scope.rglob("*.py")), path


def _iter_ts_js_scope_candidates(path: str | None = None) -> tuple[Path, list[Path], str | None]:
    workspace_root = _workspace_root()
    target_scope = _resolve_safe_path(path) if isinstance(path, str) and path.strip() else workspace_root
    allowed = {".ts", ".tsx", ".js", ".jsx"}
    if target_scope.is_file():
        return workspace_root, [target_scope], path
    return workspace_root, sorted(candidate for candidate in target_scope.rglob("*") if candidate.is_file() and candidate.suffix in allowed), path


def _find_symbol_result(name: str, path: str | None = None, kind: str | None = None, container: str | None = None) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    workspace_root, python_candidates, path_scope = _iter_python_scope_candidates(path)
    _, ts_js_candidates, _ = _iter_ts_js_scope_candidates(path)
    matches: list[dict[str, Any]] = []

    for candidate in python_candidates:
        if not candidate.is_file() or candidate.suffix != ".py":
            continue
        relative_path = str(candidate.relative_to(workspace_root))
        try:
            symbols = _extract_python_symbols(relative_path, candidate)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for symbol in symbols:
            if symbol["name"] != name:
                continue
            if isinstance(kind, str) and kind.strip() and symbol["kind"] != kind:
                continue
            if isinstance(container, str) and container.strip() and symbol.get("container") != container:
                continue
            matches.append(symbol)

    for candidate in ts_js_candidates:
        if not candidate.is_file() or candidate.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        relative_path = str(candidate.relative_to(workspace_root))
        try:
            _, symbols, _ = _extract_ts_js_symbols(relative_path, candidate)
        except ValueError:
            continue
        for symbol in symbols:
            if symbol.get("name") != name:
                continue
            if isinstance(kind, str) and kind.strip() and symbol.get("kind") != kind:
                continue
            if isinstance(container, str) and container.strip() and symbol.get("container") != container:
                continue
            matches.append(symbol)

    languages = {candidate.suffix for candidate in python_candidates if candidate.is_file()} | {candidate.suffix for candidate in ts_js_candidates if candidate.is_file()}
    language = "python" if languages == {".py"} else "typescript_javascript" if languages else "python"
    return {
        "name": name,
        "path_scope": path_scope,
        "kind": kind,
        "container": container,
        "language": language,
        "match_count": len(matches),
        "matches": matches,
    }


def _find_references_result(name: str, path: str | None = None) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    py_workspace_root, py_candidates, path_scope = _iter_python_scope_candidates(path)
    ts_workspace_root, ts_js_candidates, _ = _iter_ts_js_scope_candidates(path)
    references: list[dict[str, Any]] = []

    for candidate in py_candidates:
        if not candidate.is_file() or candidate.suffix != ".py":
            continue
        relative_path = str(candidate.relative_to(py_workspace_root))
        try:
            source = candidate.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        definition_locations: set[tuple[int, int]] = set()
        for symbol in _extract_python_symbols(relative_path, candidate):
            if symbol["name"] == name:
                definition_locations.add((symbol["line_start"], 0))

        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name:
                lineno = getattr(node, "lineno", None)
                col = getattr(node, "col_offset", None)
                if not isinstance(lineno, int) or not isinstance(col, int):
                    continue
                if (lineno, 0) in definition_locations and col == 0:
                    continue
                line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
                preview = line_text.strip()
                if len(preview) > 160:
                    preview = preview[:159].rstrip() + "…"
                references.append(
                    {
                        "path": relative_path,
                        "line": lineno,
                        "column": col,
                        "preview": preview,
                    }
                )

    for candidate in ts_js_candidates:
        if not candidate.is_file() or candidate.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        relative_path = str(candidate.relative_to(ts_workspace_root))
        try:
            _, _, candidate_references = _extract_ts_js_symbols(relative_path, candidate)
        except ValueError:
            continue
        for reference in candidate_references:
            if reference.get("name") != name:
                continue
            references.append(
                {
                    "path": relative_path,
                    "line": reference.get("line"),
                    "column": reference.get("column"),
                    "preview": reference.get("preview"),
                }
            )

    languages = {candidate.suffix for candidate in py_candidates if candidate.is_file()} | {candidate.suffix for candidate in ts_js_candidates if candidate.is_file()}
    language = "python" if languages == {".py"} else "typescript_javascript" if languages else "python"
    return {
        "name": name,
        "path_scope": path_scope,
        "language": language,
        "reference_count": len(references),
        "references": references,
    }


def _read_symbol_body_result(path: str, name: str, kind: str | None = None, container: str | None = None) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    target = _resolve_safe_file_path(path)
    source = target.read_text(encoding="utf-8")
    lines = source.splitlines()

    if target.suffix == ".py":
        language = "python"
        symbols = _extract_python_symbols(path, target, include_nodes=True)
    elif target.suffix in {".ts", ".tsx", ".js", ".jsx"}:
        language, symbols, _ = _extract_ts_js_symbols(path, target)
    else:
        raise ValueError("read_symbol_body currently supports Python, TypeScript, TSX, JavaScript, and JSX files only")

    filtered = []
    for symbol in symbols:
        if symbol["name"] != name:
            continue
        if isinstance(kind, str) and kind.strip() and symbol["kind"] != kind:
            continue
        if isinstance(container, str) and container.strip() and symbol.get("container") != container:
            continue
        filtered.append(symbol)
    if not filtered:
        return {
            "ok": False,
            "path": path,
            "name": name,
            "kind": kind,
            "container": container,
            "failure_layer": "tool_semantic",
            "failure_kind": "symbol_not_found",
        }
    if len(filtered) > 1:
        return {
            "ok": False,
            "path": path,
            "name": name,
            "kind": kind,
            "container": container,
            "failure_layer": "tool_semantic",
            "failure_kind": "symbol_ambiguous",
            "match_count": len(filtered),
            "disambiguation_hint": "Provide a narrower path or a more specific symbol target (for example container) to disambiguate this symbol.",
            "matches": [
                {
                    "path": symbol["path"],
                    "name": symbol["name"],
                    "kind": symbol["kind"],
                    "line_start": symbol["line_start"],
                    "line_end": symbol["line_end"],
                    "container": symbol["container"],
                }
                for symbol in filtered
            ],
        }
    symbol = filtered[0]
    line_start = symbol["line_start"]
    line_end = symbol["line_end"]
    body = "\n".join(lines[line_start - 1:line_end])
    header = lines[line_start - 1] if 0 < line_start <= len(lines) else ""
    return {
        "ok": True,
        "path": path,
        "language": language,
        "name": symbol["name"],
        "kind": symbol["kind"],
        "container": symbol["container"],
        "requested_container": container,
        "line_start": line_start,
        "line_end": line_end,
        "header": header,
        "body": body,
        "symbol": {
            "path": symbol["path"],
            "name": symbol["name"],
            "kind": symbol["kind"],
            "line_start": line_start,
            "line_end": line_end,
            "container": symbol["container"],
        },
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


def _apply_unified_patch_result(path: str, patch: str) -> dict[str, Any]:
    result = apply_unified_patch_to_file(workspace_root=_workspace_root(), path=path, patch=patch)
    if not result.get("ok"):
        structured = {
            "mutation_kind": "apply_unified_patch",
            "path": path,
            "failure_layer": result.get("failure_layer", "tool_semantic"),
            "failure_kind": result.get("failure_kind", "patch_apply_failed"),
            "change_summary": result.get("change_summary"),
            "applied_hunk_count": result.get("applied_hunk_count", 0),
        }
        failed_hunk = result.get("failed_hunk")
        if failed_hunk is not None:
            structured["failed_hunk"] = failed_hunk
        return structured
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
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_symbols_overview",
            description="Return a structured symbol overview for a Python source file using Python AST parsing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative Python file path."}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="find_symbol",
            description="Find symbol definitions across the workspace or within an optional path scope using the current multi-language first slice, with optional container-based filtering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact symbol name to search for."},
                    "path": {"type": "string", "description": "Optional workspace-relative file or directory scope."},
                    "kind": {"type": "string", "description": "Optional symbol kind filter, for example class, function, async_function, or method."},
                    "container": {"type": "string", "description": "Optional container/class name filter for repeated method or nested symbol names."}
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="find_references",
            description="Find candidate Python identifier references across the workspace or within an optional path scope.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact identifier name to search for."},
                    "path": {"type": "string", "description": "Optional workspace-relative file or directory scope."}
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="read_symbol_body",
            description="Read the full body of one symbol from a workspace-relative file using AST-derived or language-helper span boundaries, with optional container-based disambiguation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative Python file path."},
                    "name": {"type": "string", "description": "Exact symbol name to read."},
                    "kind": {"type": "string", "description": "Optional symbol kind filter, for example class, function, async_function, or method."},
                    "container": {"type": "string", "description": "Optional container/class name used to disambiguate repeated methods or nested symbol names."}
                },
                "required": ["path", "name"],
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
        types.Tool(
            name="todo_write",
            description="Replace the current session-scoped structured todo list.",
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
                                "priority": {},
                            },
                            "required": ["content"],
                            "additionalProperties": True,
                        },
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
            name="web_fetch",
            description="Fetch remote web content from an http(s) URL and return bounded extracted text plus metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully qualified http(s) URL to fetch."},
                    "max_chars": {"type": "integer", "description": "Maximum number of characters to return from normalized content."},
                    "format_hint": {"type": "string", "description": "Optional hint such as html, markdown, text, or json."},
                    "extract_main_text": {"type": "boolean", "description": "Prefer main/article/body extraction for HTML before text normalization."},
                },
                "required": ["url"],
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
    if name == "get_symbols_overview":
        return _get_symbols_overview_result(path)
    if name == "find_symbol":
        return _find_symbol_result(arguments.get("name"), path, arguments.get("kind"), arguments.get("container"))
    if name == "find_references":
        return _find_references_result(arguments.get("name"), path)
    if name == "read_symbol_body":
        return _read_symbol_body_result(path, arguments.get("name"), arguments.get("kind"), arguments.get("container"))
    if name == "replace_in_file":
        return _replace_in_file_result(path, arguments.get("old_text"), arguments.get("new_text"))
    if name == "apply_unified_patch":
        return _apply_unified_patch_result(path, arguments.get("patch"))
    if name == "todo_write":
        return _todo_write_result(arguments.get("items"))
    if name == "todo_read":
        return _todo_read_result()
    if name == "web_fetch":
        return _web_fetch_result(
            arguments.get("url"),
            arguments.get("max_chars"),
            arguments.get("format_hint"),
            arguments.get("extract_main_text"),
        )
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
