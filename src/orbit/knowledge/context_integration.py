from __future__ import annotations

from typing import TYPE_CHECKING

from orbit.knowledge.models import KnowledgeBundle

if TYPE_CHECKING:
    from orbit.runtime.execution.context_assembly import ContextFragment


def _truncate(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def knowledge_preflight_to_context_fragments(*, availability: dict, vault_metadata: dict | None = None) -> list["ContextFragment"]:
    from orbit.runtime.execution.context_assembly import ContextFragment

    fragments: list[ContextFragment] = []
    warnings = availability.get("warnings") if isinstance(availability, dict) else []
    checks = availability.get("checks") if isinstance(availability, dict) else {}
    fragments.append(
        ContextFragment(
            fragment_name="knowledge_availability_preflight",
            visibility_scope="knowledge_preflight",
            content=(
                f"Knowledge availability: {availability.get('availability_level', 'unknown')}\n"
                f"Recommended mode: {availability.get('recommended_mode', 'unknown')}\n"
                f"Vault root configured: {availability.get('vault_root_configured')}\n"
                f"Vault root exists: {availability.get('vault_root_exists')}\n"
                f"Vault root readable: {availability.get('vault_root_readable')}\n"
                f"Obsidian CLI found: {availability.get('obsidian_cli_found')}"
            ).strip(),
            priority=62,
            metadata={
                "availability_level": availability.get("availability_level"),
                "recommended_mode": availability.get("recommended_mode"),
                "warnings": list(warnings) if isinstance(warnings, list) else [],
                "checks": checks if isinstance(checks, dict) else {},
            },
        )
    )
    if vault_metadata:
        top_level_entries = vault_metadata.get("top_level_entries") if isinstance(vault_metadata, dict) else []
        top_level_hint = ", ".join(
            str(item.get("name")) for item in (top_level_entries or [])[:5] if isinstance(item, dict) and item.get("name")
        )
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_vault_metadata",
                visibility_scope="knowledge_preflight",
                content=(
                    f"Vault: {vault_metadata.get('vault_name', 'unknown')}\n"
                    f"Scope: {vault_metadata.get('path_scope', '') or '(root)'}\n"
                    f"Note count: {vault_metadata.get('note_count', 'unknown')}\n"
                    f"Directory count: {vault_metadata.get('directory_count', 'unknown')}\n"
                    f"Latest modified: {vault_metadata.get('latest_modified_at_epoch', 'unknown')}\n"
                    f"Top-level structure hint: {top_level_hint or '(none)'}"
                ).strip(),
                priority=61,
                metadata={
                    "vault_name": vault_metadata.get("vault_name"),
                    "path_scope": vault_metadata.get("path_scope"),
                    "note_count": vault_metadata.get("note_count"),
                    "directory_count": vault_metadata.get("directory_count"),
                },
            )
        )
    return fragments


def knowledge_bundle_to_context_fragments(bundle: KnowledgeBundle) -> list["ContextFragment"]:
    from orbit.runtime.execution.context_assembly import ContextFragment
    fragments: list[ContextFragment] = []
    if bundle.summary:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_guidance_summary",
                visibility_scope="knowledge_guidance",
                content=_truncate(bundle.summary, 400),
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
                content=_truncate(bundle.planning_guidance, 400),
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
                    f"Primary anchor: {_truncate(bundle.primary_anchor.note.title, 120)}\n"
                    f"Type: {bundle.primary_anchor.anchor_kind}\n"
                    f"Summary: {_truncate(bundle.primary_anchor.note.summary, 240)}"
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
                content="\n".join(
                    f"- {_truncate(note.title, 120)}: {_truncate(note.summary, 180)}"
                    for note in bundle.decision_notes[:2]
                ),
                priority=56,
                metadata={"count": min(len(bundle.decision_notes), 2)},
            )
        )
    if bundle.procedural_notes:
        fragments.append(
            ContextFragment(
                fragment_name="knowledge_procedural_notes",
                visibility_scope="knowledge_retrieval",
                content="\n".join(
                    f"- {_truncate(note.title, 120)}: {_truncate(note.summary, 180)}"
                    for note in bundle.procedural_notes[:2]
                ),
                priority=55,
                metadata={"count": min(len(bundle.procedural_notes), 2)},
            )
        )
    return fragments
