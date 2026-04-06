from __future__ import annotations

from typing import Any

from orbit.knowledge.models import KnowledgeNote
from orbit.tools.base import ToolResult


def _canonical_note_type(raw_type: str) -> str:
    value = (raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "project": "project",
        "decision": "decision",
        "procedure": "procedure",
        "procedural": "procedure",
        "principle": "principle",
        "episode": "episode",
        "entity": "entity",
        "index": "index",
        "moc": "index",
        "memory": "generic",
        "note": "generic",
        "generic": "generic",
    }
    return mapping.get(value, "generic")


class ObsidianKnowledgeService:
    """Thin knowledge-oriented adapter over the Obsidian MCP capability surface."""

    def __init__(self, *, vault_root: str, max_read_chars: int | None = None, max_results: int | None = None):
        from orbit.runtime.mcp.bootstrap import bootstrap_local_obsidian_mcp_server
        from orbit.runtime.mcp.client import build_mcp_client

        self.vault_root = vault_root
        self.bootstrap = bootstrap_local_obsidian_mcp_server(
            vault_root=vault_root,
            max_read_chars=max_read_chars,
            max_results=max_results,
        )
        self.client = build_mcp_client(self.bootstrap)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return self.client.call_tool(tool_name, arguments)

    def list_notes(self, *, path: str | None = None, recursive: bool = True, max_results: int | None = None) -> dict[str, Any]:
        result = self.call_tool(
            "obsidian_list_notes",
            {
                **({"path": path} if path else {}),
                "recursive": recursive,
                **({"maxResults": max_results} if max_results is not None else {}),
            },
        )
        return self._structured(result)

    def read_note(self, *, path: str, include_raw_content: bool = False, max_chars: int | None = None) -> KnowledgeNote:
        result = self.call_tool(
            "obsidian_read_note",
            {
                "path": path,
                "includeRawContent": include_raw_content,
                **({"maxChars": max_chars} if max_chars is not None else {}),
            },
        )
        structured = self._structured(result)
        return self._knowledge_note_from_structured(structured)

    def search_notes(self, *, query: str, path: str | None = None, max_results: int | None = None, search_in: list[str] | None = None) -> dict[str, Any]:
        result = self.call_tool(
            "obsidian_search_notes",
            {
                "query": query,
                **({"path": path} if path else {}),
                **({"maxResults": max_results} if max_results is not None else {}),
                **({"searchIn": search_in} if search_in else {}),
            },
        )
        return self._structured(result)

    def get_note_links(self, *, path: str) -> dict[str, Any]:
        result = self.call_tool("obsidian_get_note_links", {"path": path})
        return self._structured(result)

    def hydrate_match_note(self, match: dict[str, Any]) -> KnowledgeNote:
        path = str(match.get("path") or "").strip()
        note = self.read_note(path=path, include_raw_content=False)
        note.metadata["match_surfaces"] = list(match.get("match_surfaces") or [])
        note.metadata["score_hint"] = match.get("score_hint")
        return note

    def _structured(self, result: ToolResult) -> dict[str, Any]:
        if not result.ok:
            raise ValueError(result.content or "obsidian MCP call failed")
        data = result.data if isinstance(result.data, dict) else {}
        raw_result = data.get("raw_result") if isinstance(data, dict) else {}
        structured = raw_result.get("structuredContent") if isinstance(raw_result, dict) else None
        if not isinstance(structured, dict):
            raise ValueError("obsidian MCP result missing structuredContent")
        return structured

    def _knowledge_note_from_structured(self, structured: dict[str, Any]) -> KnowledgeNote:
        return KnowledgeNote(
            path=str(structured.get("path") or ""),
            title=str(structured.get("title") or ""),
            note_type=_canonical_note_type(str(structured.get("note_type_hint") or "generic")),
            summary=str(structured.get("summary") or ""),
            frontmatter=structured.get("frontmatter") if isinstance(structured.get("frontmatter"), dict) else {},
            tags=[str(tag) for tag in structured.get("tags", []) if str(tag).strip()],
            links=[item for item in structured.get("links", []) if isinstance(item, dict)],
            headings=[item for item in structured.get("headings", []) if isinstance(item, dict)],
            raw_excerpt=structured.get("raw_content") if isinstance(structured.get("raw_content"), str) else None,
            metadata={
                "content_chars": structured.get("content_chars"),
                "truncated": structured.get("truncated"),
            },
        )
