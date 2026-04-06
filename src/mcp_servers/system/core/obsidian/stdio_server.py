from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

SERVER_NAME = "obsidian"
SERVER_VERSION = "0.1.0"
VAULT_ROOT_ENV = "ORBIT_OBSIDIAN_VAULT_ROOT"
MAX_READ_CHARS_ENV = "ORBIT_OBSIDIAN_MAX_READ_CHARS"
MAX_RESULTS_ENV = "ORBIT_OBSIDIAN_MAX_RESULTS"
DEFAULT_MAX_READ_CHARS = 12000
DEFAULT_MAX_RESULTS = 20

server = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions="Bounded read-only Obsidian MCP server for ORBIT knowledge-management first slice.",
)


def _vault_root() -> Path:
    raw = os.environ.get(VAULT_ROOT_ENV, "").strip()
    if not raw:
        raise ValueError(f"missing required environment variable: {VAULT_ROOT_ENV}")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"vault root is invalid: {root}")
    return root


def _max_read_chars() -> int:
    raw = os.environ.get(MAX_READ_CHARS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_READ_CHARS
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{MAX_READ_CHARS_ENV} must be > 0")
    return value


def _max_results() -> int:
    raw = os.environ.get(MAX_RESULTS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_RESULTS
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{MAX_RESULTS_ENV} must be > 0")
    return value


def _resolve_safe_path(path: str | None = None) -> Path:
    root = _vault_root()
    if path is None or not str(path).strip():
        return root
    candidate = Path(str(path))
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes vault root") from exc
    if not target.exists():
        raise ValueError("path not found")
    return target


def _resolve_safe_note_path(path: str) -> Path:
    target = _resolve_safe_path(path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise ValueError("path is not a markdown note")
    return target


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", " ", text, flags=re.DOTALL)


def _extract_frontmatter_and_body(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw_frontmatter = text[4:end]
    body = text[end + 5:]
    frontmatter: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in raw_frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            frontmatter.setdefault(current_key, [])
            if isinstance(frontmatter[current_key], list):
                frontmatter[current_key].append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if not value:
            frontmatter[current_key] = []
            continue
        lowered = value.lower()
        if lowered in {"true", "false"}:
            frontmatter[current_key] = lowered == "true"
        else:
            frontmatter[current_key] = value.strip('"\'')
    return frontmatter, body


def _extract_tags(text: str, frontmatter: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    fm_tags = frontmatter.get("tags")
    if isinstance(fm_tags, str) and fm_tags.strip():
        tags.append(fm_tags.strip())
    elif isinstance(fm_tags, list):
        tags.extend(str(item).strip() for item in fm_tags if str(item).strip())
    for match in re.findall(r"(?<!\w)#([\w\-/]+)", text):
        tags.append(match)
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped


def _extract_headings(body: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        text = stripped[level:].strip()
        if text:
            headings.append({"level": level, "text": text})
    return headings


def _extract_links(body: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for match in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", body):
        target = match.group(1).strip()
        if target:
            links.append({"target": target, "kind": "wikilink"})
    return links


def _note_type_hint(path: Path, title: str, frontmatter: dict[str, Any]) -> str:
    explicit = frontmatter.get("type") or frontmatter.get("note_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower().replace(" ", "_")
    joined = f"{path.as_posix()} {title}".lower()
    if "project" in joined:
        return "project"
    if "decision" in joined:
        return "decision"
    if "procedure" in joined:
        return "procedure"
    if "episode" in joined:
        return "episode"
    if "entity" in joined:
        return "entity"
    if "principle" in joined:
        return "principle"
    if "index" in joined or "moc" in joined:
        return "index"
    return "generic"


def _build_summary(body: str, *, max_chars: int = 600) -> str:
    cleaned = _strip_code_fences(body)
    cleaned = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^#+\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars].rstrip()


def _list_notes_result(path: str | None = None, recursive: bool = False, max_results: int | None = None) -> dict[str, Any]:
    root = _vault_root()
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    limit = max_results if isinstance(max_results, int) and max_results > 0 else _max_results()
    pattern = "**/*.md" if recursive else "*.md"
    note_paths = sorted(target.glob(pattern))
    notes: list[dict[str, Any]] = []
    truncated = len(note_paths) > limit
    for note_path in note_paths[:limit]:
        try:
            stat = note_path.stat()
        except OSError:
            continue
        title = note_path.stem
        notes.append(
            {
                "path": str(note_path.relative_to(root)),
                "title": title,
                "note_type_hint": _note_type_hint(note_path.relative_to(root), title, {}),
                "modified_at_epoch": stat.st_mtime,
            }
        )
    return {
        "path": str(target.relative_to(root)) if target != root else "",
        "recursive": bool(recursive),
        "note_count": len(notes),
        "truncated": truncated,
        "notes": notes,
    }


def _read_note_result(path: str, include_raw_content: bool | None = None, max_chars: int | None = None) -> dict[str, Any]:
    root = _vault_root()
    target = _resolve_safe_note_path(path)
    text = target.read_text(encoding="utf-8")
    frontmatter, body = _extract_frontmatter_and_body(text)
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else _max_read_chars()
    raw_content = text[:limit] if bool(include_raw_content) else None
    truncated = len(text) > limit if bool(include_raw_content) else False
    rel = target.relative_to(root)
    title = target.stem
    tags = _extract_tags(text, frontmatter)
    headings = _extract_headings(body)
    links = _extract_links(body)
    summary = _build_summary(body)
    return {
        "path": str(rel),
        "title": title,
        "note_type_hint": _note_type_hint(rel, title, frontmatter),
        "frontmatter": frontmatter,
        "tags": tags,
        "headings": headings,
        "links": links,
        "summary": summary,
        "raw_content": raw_content,
        "truncated": truncated,
        "content_chars": min(len(text), limit) if bool(include_raw_content) else len(text),
    }


def _search_notes_result(query: str, path: str | None = None, max_results: int | None = None, search_in: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    root = _vault_root()
    target = _resolve_safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    limit = max_results if isinstance(max_results, int) and max_results > 0 else _max_results()
    surfaces = set(search_in or ["title", "frontmatter", "tags", "summary", "content", "path"])
    raw_tokens = [token for token in re.findall(r"[a-zA-Z0-9_\-]+", query.lower()) if token]
    stopwords = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i", "in", "is", "it", "need", "of", "on", "or", "that", "the", "this", "to", "use", "want", "with"}
    tokens = [token for token in raw_tokens if token not in stopwords and len(token) >= 3]
    if not tokens:
        tokens = [query.lower().strip()]

    matches: list[dict[str, Any]] = []
    for note_path in sorted(target.rglob("*.md")):
        text = note_path.read_text(encoding="utf-8")
        frontmatter, body = _extract_frontmatter_and_body(text)
        title = note_path.stem
        rel = str(note_path.relative_to(root))
        summary = _build_summary(body)
        tags = _extract_tags(text, frontmatter)
        frontmatter_text = json.dumps(frontmatter, ensure_ascii=False).lower()
        body_lower = body.lower()
        summary_lower = summary.lower()
        title_lower = title.lower()
        path_lower = rel.lower()
        tags_lower = [tag.lower() for tag in tags]

        matched_tokens: list[str] = []
        hit_surfaces: list[str] = []
        score_hint = 0.0
        for token in tokens:
            token_hit = False
            if "title" in surfaces and token in title_lower:
                token_hit = True
                score_hint += 1.2
                if "title" not in hit_surfaces:
                    hit_surfaces.append("title")
            if "path" in surfaces and token in path_lower:
                token_hit = True
                score_hint += 0.6
                if "path" not in hit_surfaces:
                    hit_surfaces.append("path")
            if "summary" in surfaces and token in summary_lower:
                token_hit = True
                score_hint += 0.8
                if "summary" not in hit_surfaces:
                    hit_surfaces.append("summary")
            if "content" in surfaces and token in body_lower:
                token_hit = True
                score_hint += 0.3
                if "content" not in hit_surfaces:
                    hit_surfaces.append("content")
            if "tags" in surfaces and any(token in tag for tag in tags_lower):
                token_hit = True
                score_hint += 0.5
                if "tags" not in hit_surfaces:
                    hit_surfaces.append("tags")
            if "frontmatter" in surfaces and token in frontmatter_text:
                token_hit = True
                score_hint += 0.4
                if "frontmatter" not in hit_surfaces:
                    hit_surfaces.append("frontmatter")
            if token_hit and token not in matched_tokens:
                matched_tokens.append(token)

        if not matched_tokens:
            continue

        note_type_hint = _note_type_hint(note_path.relative_to(root), title, frontmatter)
        if "project" in tokens and note_type_hint == "project":
            score_hint += 1.0
        if ("decision" in tokens or "decisions" in tokens) and note_type_hint == "decision":
            score_hint += 1.0
        if any(token in {"procedure", "workflow", "guide", "guidance", "steps", "step"} for token in tokens) and note_type_hint == "procedure":
            score_hint += 1.0

        matches.append(
            {
                "path": rel,
                "title": title,
                "note_type_hint": note_type_hint,
                "match_surfaces": hit_surfaces,
                "matched_tokens": matched_tokens,
                "preview": summary[:240],
                "score_hint": round(score_hint, 4),
            }
        )

    matches.sort(key=lambda item: float(item.get("score_hint") or 0.0), reverse=True)
    truncated = len(matches) > limit
    visible = matches[:limit]
    return {
        "query": query,
        "query_tokens": tokens,
        "path_scope": str(target.relative_to(root)) if target != root else "",
        "match_count": len(visible),
        "truncated": truncated,
        "matches": visible,
    }


def _get_note_links_result(path: str) -> dict[str, Any]:
    root = _vault_root()
    target = _resolve_safe_note_path(path)
    text = target.read_text(encoding="utf-8")
    _, body = _extract_frontmatter_and_body(text)
    raw_links = _extract_links(body)
    indexed: dict[str, str] = {}
    for candidate in root.rglob("*.md"):
        indexed[candidate.stem] = str(candidate.relative_to(root))
    links: list[dict[str, Any]] = []
    for item in raw_links:
        target_name = str(item.get("target") or "").strip()
        links.append(
            {
                "target": target_name,
                "resolved_path": indexed.get(target_name),
                "kind": item.get("kind") or "wikilink",
            }
        )
    return {
        "path": str(target.relative_to(root)),
        "link_count": len(links),
        "links": links,
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="obsidian_list_notes",
            description="List markdown notes in the configured Obsidian vault or a scoped subdirectory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional vault-relative directory path."},
                    "recursive": {"type": "boolean", "description": "Recurse into subdirectories."},
                    "maxResults": {"type": "integer", "description": "Maximum number of notes to return."},
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_read_note",
            description="Read a markdown note from the configured Obsidian vault and return structured metadata plus optional raw content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Vault-relative note path."},
                    "includeRawContent": {"type": "boolean", "description": "Include bounded raw markdown content."},
                    "maxChars": {"type": "integer", "description": "Maximum number of raw markdown characters to include."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_search_notes",
            description="Search markdown notes in the configured Obsidian vault across bounded note surfaces.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "path": {"type": "string", "description": "Optional vault-relative directory scope."},
                    "maxResults": {"type": "integer", "description": "Maximum number of results to return."},
                    "searchIn": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["title", "frontmatter", "tags", "summary", "content", "path"],
                        },
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_get_note_links",
            description="Return outbound wiki links for a vault-relative markdown note and best-effort resolved note paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Vault-relative note path."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "obsidian_list_notes":
        return _list_notes_result(arguments.get("path"), bool(arguments.get("recursive", False)), arguments.get("maxResults"))
    if name == "obsidian_read_note":
        return _read_note_result(arguments.get("path"), arguments.get("includeRawContent"), arguments.get("maxChars"))
    if name == "obsidian_search_notes":
        return _search_notes_result(arguments.get("query"), arguments.get("path"), arguments.get("maxResults"), arguments.get("searchIn"))
    if name == "obsidian_get_note_links":
        return _get_note_links_result(arguments.get("path"))
    raise ValueError(f"unknown tool: {name}")


async def main() -> None:
    _vault_root()
    _max_read_chars()
    _max_results()
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
