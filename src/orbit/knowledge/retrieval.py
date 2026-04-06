from __future__ import annotations

import re

from orbit.knowledge.models import KnowledgeAnchor, KnowledgeBundle, KnowledgeNote, KnowledgeQuery
from orbit.knowledge.obsidian_service import ObsidianKnowledgeService


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i", "in", "is", "it", "need", "of", "on", "or", "that", "the", "this", "to", "use", "want", "with",
}


def _tokenize_query(text: str) -> list[str]:
    raw = [token for token in re.findall(r"[a-zA-Z0-9_\-]+", text.lower()) if token]
    return [token for token in raw if token not in _STOPWORDS and len(token) >= 3]


def _preferred_note_types(tokens: list[str]) -> list[str]:
    preferred: list[str] = []
    if any(token in {"project", "orbit"} for token in tokens):
        preferred.append("project")
    if any(token in {"decision", "decisions", "why"} for token in tokens):
        preferred.append("decision")
    if any(token in {"procedure", "procedures", "workflow", "steps", "step", "guide", "guidance", "how"} for token in tokens):
        preferred.append("procedure")
    if any(token in {"principle", "principles"} for token in tokens):
        preferred.append("principle")
    if any(token in {"episode", "history", "context"} for token in tokens):
        preferred.append("episode")
    deduped: list[str] = []
    for item in preferred:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _preferred_anchor_kind(note: KnowledgeNote) -> str:
    note_type = note.note_type.lower()
    if note_type in {"project", "decision", "procedure", "principle", "episode", "entity", "index"}:
        return note_type
    return "generic"


def _group_notes(notes: list[KnowledgeNote]) -> dict[str, list[KnowledgeNote]]:
    grouped = {
        "project": [],
        "decision": [],
        "procedure": [],
        "principle": [],
        "episode": [],
    }
    for note in notes:
        key = note.note_type.lower()
        if key == "procedural":
            key = "procedure"
        if key in grouped:
            grouped[key].append(note)
    return grouped


def _dedupe_notes(notes: list[KnowledgeNote]) -> list[KnowledgeNote]:
    deduped: list[KnowledgeNote] = []
    seen: set[str] = set()
    for note in notes:
        if note.path in seen:
            continue
        seen.add(note.path)
        deduped.append(note)
    return deduped


def _score_note(note: KnowledgeNote, *, tokens: list[str], preferred_types: list[str], match_surfaces: list[str] | None = None, base_score: float = 0.0) -> float:
    title = note.title.lower()
    summary = note.summary.lower()
    path = note.path.lower()
    note_type = note.note_type.lower()
    score = base_score
    for token in tokens:
        if token in title:
            score += 1.2
        if token in summary:
            score += 0.6
        if token in path:
            score += 0.5
    if note_type in preferred_types:
        score += 1.0
    planning_bias = {
        "decision": 1.1,
        "procedure": 0.95,
        "project": 0.85,
        "principle": 0.8,
        "episode": 0.35,
        "entity": 0.25,
        "index": 0.15,
        "generic": 0.0,
    }
    score += planning_bias.get(note_type, 0.0)
    surfaces = set(match_surfaces or [])
    if "title" in surfaces:
        score += 0.8
    if "summary" in surfaces:
        score += 0.4
    if "path" in surfaces:
        score += 0.3
    if "tags" in surfaces or "frontmatter" in surfaces:
        score += 0.2
    return score


def retrieve_knowledge_bundle(*, query: KnowledgeQuery, obsidian_service: ObsidianKnowledgeService) -> KnowledgeBundle:
    tokens = _tokenize_query(query.query_text)
    preferred_types = list(query.preferred_note_types or _preferred_note_types(tokens))
    search = obsidian_service.search_notes(
        query=" ".join(tokens) if tokens else query.query_text,
        path=query.scope_path,
        max_results=max(query.limit * 3, 8),
        search_in=["title", "frontmatter", "tags", "summary", "path"],
    )
    matches = list(search.get("matches") or [])
    scored_candidates: list[tuple[float, KnowledgeNote, dict]] = []
    primary_anchor: KnowledgeAnchor | None = None

    for match in matches:
        note = obsidian_service.hydrate_match_note(match)
        score = _score_note(
            note,
            tokens=tokens,
            preferred_types=preferred_types,
            match_surfaces=[str(item) for item in match.get("match_surfaces", [])],
            base_score=float(match.get("score_hint") or 0.0),
        )
        scored_candidates.append((score, note, match))

    if not scored_candidates and tokens:
        inventory = obsidian_service.list_notes(path=query.scope_path, recursive=True, max_results=max(query.limit * 6, 24))
        for item in inventory.get("notes", []):
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            try:
                note = obsidian_service.read_note(path=path, include_raw_content=False)
            except Exception:
                continue
            score = _score_note(note, tokens=tokens, preferred_types=preferred_types, match_surfaces=["inventory"], base_score=0.0)
            if score > 0:
                scored_candidates.append((score, note, {"match_surfaces": ["inventory"]}))

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    hydrated = [item[1] for item in scored_candidates[: query.limit]]
    if scored_candidates:
        top_score, top_note, top_match = scored_candidates[0]
        primary_anchor = KnowledgeAnchor(
            note=top_note,
            anchor_kind=_preferred_anchor_kind(top_note),
            match_surfaces=[str(item) for item in top_match.get("match_surfaces", [])],
            score=float(top_score),
            rationale="highest-scoring first-slice obsidian anchor after token-aware ranking",
        )

    expanded: list[KnowledgeNote] = []
    if primary_anchor is not None:
        links = obsidian_service.get_note_links(path=primary_anchor.note.path)
        for link in links.get("links", [])[: max(0, query.limit - 1)]:
            resolved_path = link.get("resolved_path")
            if not isinstance(resolved_path, str) or not resolved_path.strip():
                continue
            try:
                expanded.append(obsidian_service.read_note(path=resolved_path, include_raw_content=False))
            except Exception:
                continue

    all_notes = _dedupe_notes(hydrated + expanded)
    grouped = _group_notes(all_notes)

    summary_parts: list[str] = []
    if primary_anchor is not None:
        summary_parts.append(f"Primary knowledge anchor: {primary_anchor.note.title} ({primary_anchor.anchor_kind}).")
    if grouped["decision"]:
        summary_parts.append("Relevant decisions: " + ", ".join(note.title for note in grouped["decision"][:3]) + ".")
    if grouped["procedure"]:
        summary_parts.append("Relevant procedures: " + ", ".join(note.title for note in grouped["procedure"][:3]) + ".")
    if grouped["project"]:
        summary_parts.append("Relevant projects: " + ", ".join(note.title for note in grouped["project"][:3]) + ".")

    guidance_parts: list[str] = []
    if primary_anchor is not None:
        guidance_parts.append(
            f"Use {primary_anchor.note.title} as the main stable knowledge anchor for planning around '{query.query_text}'."
        )
    if grouped["decision"]:
        guidance_parts.append("Check decision notes before changing behavior that could conflict with established direction.")
    if grouped["procedure"]:
        guidance_parts.append("Prefer procedure notes as execution guidance before inventing a new workflow.")
    if grouped["project"]:
        guidance_parts.append("Keep project notes in view to preserve scope and current intent.")

    return KnowledgeBundle(
        query_text=query.query_text,
        primary_anchor=primary_anchor,
        supporting_notes=all_notes,
        project_notes=grouped["project"],
        decision_notes=grouped["decision"],
        procedural_notes=grouped["procedure"],
        principle_notes=grouped["principle"],
        episode_notes=grouped["episode"],
        summary=" ".join(summary_parts).strip(),
        planning_guidance=" ".join(guidance_parts).strip(),
        confidence=primary_anchor.score if primary_anchor is not None else 0.0,
        metadata={
            "match_count": len(matches),
            "expanded_count": len(expanded),
            "scope_path": query.scope_path,
            "retrieval_mode": "obsidian_anchor_bundle_v1",
            "query_tokens": tokens,
            "preferred_note_types": preferred_types,
        },
    )
