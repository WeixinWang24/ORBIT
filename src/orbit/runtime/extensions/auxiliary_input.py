from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from orbit.models import ConversationMessage, ConversationSession
from orbit.runtime.execution.context_assembly import ContextFragment
from orbit.knowledge.context_integration import knowledge_bundle_to_context_fragments, knowledge_preflight_to_context_fragments
from orbit.knowledge.models import KnowledgeQuery
from orbit.knowledge.obsidian_service import ObsidianKnowledgeService
from orbit.knowledge.retrieval import retrieve_knowledge_bundle


@dataclass
class AuxiliaryInputCollection:
    fragments: list[ContextFragment]
    metadata: dict
    timings: dict[str, float]


class AuxiliaryInputCollector(Protocol):
    def collect(
        self,
        *,
        session: ConversationSession | None,
        messages: list[ConversationMessage],
        runtime_profile: str,
        query_text: str,
    ) -> AuxiliaryInputCollection:
        ...


class NoOpAuxiliaryInputCollector:
    def collect(
        self,
        *,
        session: ConversationSession | None,
        messages: list[ConversationMessage],
        runtime_profile: str,
        query_text: str,
    ) -> AuxiliaryInputCollection:
        return AuxiliaryInputCollection(fragments=[], metadata={}, timings={})


class DetachedKnowledgeMemoryCollector:

    def __init__(self, *, enable_knowledge: bool = False, enable_memory: bool = False, memory_service=None, session_manager=None):
        self.enable_knowledge = enable_knowledge
        self.enable_memory = enable_memory
        self.memory_service = memory_service
        self.session_manager = session_manager

    def collect(
        self,
        *,
        session: ConversationSession | None,
        messages: list[ConversationMessage],
        runtime_profile: str,
        query_text: str,
    ) -> AuxiliaryInputCollection:
        fragments: list[ContextFragment] = []
        metadata: dict = {}
        timings: dict[str, float] = {
            "memory_retrieval_ms": 0.0,
            "knowledge_setup_ms": 0.0,
            "knowledge_preflight_ms": 0.0,
            "knowledge_retrieval_ms": 0.0,
        }

        if self.enable_memory and session is not None and self.memory_service is not None:
            t = time.perf_counter()
            memory_fragments = self.memory_service.retrieve_memory_fragments(
                session_id=session.session_id,
                query_text=query_text,
                limit=3,
            )
            timings["memory_retrieval_ms"] = round((time.perf_counter() - t) * 1000, 2)
            fragments.extend(memory_fragments)

        if self.enable_knowledge and session is not None and query_text.strip():
            try:
                t = time.perf_counter()
                vault_root = getattr(getattr(self.session_manager, "_obsidian_vault_root", None), "__call__", None)
                resolved_vault_root = vault_root() if callable(vault_root) else os.environ.get("ORBIT_OBSIDIAN_VAULT_ROOT", "")
                knowledge_service = ObsidianKnowledgeService(vault_root=resolved_vault_root)
                timings["knowledge_setup_ms"] = round((time.perf_counter() - t) * 1000, 2)

                t = time.perf_counter()
                availability = knowledge_service.check_availability()
                vault_metadata = None
                if availability.get("availability_level") in {"full", "vault_only"}:
                    vault_metadata = knowledge_service.get_vault_metadata(max_entries=5)
                fragments.extend(
                    knowledge_preflight_to_context_fragments(
                        availability=availability,
                        vault_metadata=vault_metadata,
                    )
                )
                timings["knowledge_preflight_ms"] = round((time.perf_counter() - t) * 1000, 2)
                metadata["last_knowledge_availability"] = availability
                if vault_metadata is not None:
                    metadata["last_knowledge_vault_metadata"] = vault_metadata

                if availability.get("availability_level") in {"full", "vault_only"}:
                    t = time.perf_counter()
                    knowledge_bundle = retrieve_knowledge_bundle(
                        query=KnowledgeQuery(query_text=query_text, limit=3),
                        obsidian_service=knowledge_service,
                    )
                    timings["knowledge_retrieval_ms"] = round((time.perf_counter() - t) * 1000, 2)
                    narrowed_fragments = knowledge_bundle_to_context_fragments(knowledge_bundle)
                    allowed_fragment_names = {
                        "knowledge_guidance_summary",
                        "knowledge_planning_guidance",
                        "knowledge_decision_notes",
                        "knowledge_procedural_notes",
                    }
                    allowed_prefixes = ("knowledge_primary_anchor:",)
                    fragments.extend(
                        fragment
                        for fragment in narrowed_fragments
                        if fragment.fragment_name in allowed_fragment_names or fragment.fragment_name.startswith(allowed_prefixes)
                    )
                    metadata["last_knowledge_bundle"] = {
                        "query_text": knowledge_bundle.query_text,
                        "confidence": knowledge_bundle.confidence,
                        "retrieval_mode": knowledge_bundle.metadata.get("retrieval_mode"),
                        "primary_anchor": knowledge_bundle.primary_anchor.note.path if knowledge_bundle.primary_anchor is not None else None,
                        "decision_note_count": len(knowledge_bundle.decision_notes),
                        "procedural_note_count": len(knowledge_bundle.procedural_notes),
                    }
            except Exception as exc:
                metadata["last_knowledge_error"] = repr(exc)

        return AuxiliaryInputCollection(fragments=fragments, metadata=metadata, timings=timings)
