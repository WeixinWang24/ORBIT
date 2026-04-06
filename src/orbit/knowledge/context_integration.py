from __future__ import annotations

from typing import TYPE_CHECKING

from orbit.knowledge.models import KnowledgeBundle

if TYPE_CHECKING:
    from orbit.runtime.execution.context_assembly import ContextFragment


def knowledge_bundle_to_context_fragments(bundle: KnowledgeBundle) -> list["ContextFragment"]:
    from orbit.runtime.execution.context_assembly import ContextFragment
    fragments: list[ContextFragment] = []
    if bundle.summary:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_guidance_summary",
                visibility_scope="knowledge_guidance",
                content=bundle.summary,
                priority=58,
                metadata={
                    "query_text": bundle.query_text,
                    "confidence": bundle.confidence,
                    "retrieval_mode": bundle.metadata.get("retrieval_mode"),
                },
            )
        )
    if bundle.planning_guidance:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_planning_guidance",
                visibility_scope="knowledge_guidance",
                content=bundle.planning_guidance,
                priority=60,
                metadata={
                    "query_text": bundle.query_text,
                    "confidence": bundle.confidence,
                    "primary_anchor": bundle.primary_anchor.note.title if bundle.primary_anchor is not None else None,
                },
            )
        )
    if bundle.primary_anchor is not None:
        fragments.append(
            ContextFragment(
                fragment_name=f"knowledge_primary_anchor:{bundle.primary_anchor.note.path}",
                visibility_scope="knowledge_retrieval",
                content=(
                    f"Primary anchor: {bundle.primary_anchor.note.title}\n"
                    f"Type: {bundle.primary_anchor.anchor_kind}\n"
                    f"Summary: {bundle.primary_anchor.note.summary}"
                ).strip(),
                priority=57,
                metadata={
                    "path": bundle.primary_anchor.note.path,
                    "title": bundle.primary_anchor.note.title,
                    "note_type": bundle.primary_anchor.note.note_type,
                    "match_surfaces": bundle.primary_anchor.match_surfaces,
                    "score": bundle.primary_anchor.score,
                },
            )
        )
    if bundle.decision_notes:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_decision_notes",
                visibility_scope="knowledge_retrieval",
                content="\n".join(f"- {note.title}: {note.summary}" for note in bundle.decision_notes[:3]),
                priority=56,
                metadata={"count": len(bundle.decision_notes)},
            )
        )
    if bundle.procedural_notes:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_procedural_notes",
                visibility_scope="knowledge_retrieval",
                content="\n".join(f"- {note.title}: {note.summary}" for note in bundle.procedural_notes[:3]),
                priority=55,
                metadata={"count": len(bundle.procedural_notes)},
            )
        )
    return fragments
