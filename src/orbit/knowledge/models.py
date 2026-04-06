from __future__ import annotations

from pydantic import Field

from orbit.models.core import OrbitBaseModel


class KnowledgeNote(OrbitBaseModel):
    path: str
    title: str
    note_type: str = "generic"
    summary: str = ""
    frontmatter: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    headings: list[dict] = Field(default_factory=list)
    raw_excerpt: str | None = None
    source: str = "obsidian"
    metadata: dict = Field(default_factory=dict)


class KnowledgeAnchor(OrbitBaseModel):
    note: KnowledgeNote
    anchor_kind: str = "generic"
    match_surfaces: list[str] = Field(default_factory=list)
    score: float = 0.0
    rationale: str | None = None


class KnowledgeQuery(OrbitBaseModel):
    query_text: str
    scope_path: str | None = None
    preferred_note_types: list[str] = Field(default_factory=list)
    limit: int = 5


class KnowledgeBundle(OrbitBaseModel):
    query_text: str
    primary_anchor: KnowledgeAnchor | None = None
    supporting_notes: list[KnowledgeNote] = Field(default_factory=list)
    project_notes: list[KnowledgeNote] = Field(default_factory=list)
    decision_notes: list[KnowledgeNote] = Field(default_factory=list)
    procedural_notes: list[KnowledgeNote] = Field(default_factory=list)
    principle_notes: list[KnowledgeNote] = Field(default_factory=list)
    episode_notes: list[KnowledgeNote] = Field(default_factory=list)
    summary: str = ""
    planning_guidance: str = ""
    confidence: float = 0.0
    metadata: dict = Field(default_factory=dict)
