"""Memory extraction and retrieval helpers for ORBIT first-slice persistence.

This module now provides a bounded but real first semantic slice:
- derive session and durable memory records from transcript-visible turns
- persist derivative embeddings with hash-based refresh/dedupe behavior
- expose hybrid retrieval (embedding + lexical overlap)
- preserve the boundary that retrieved memory enters prompt assembly as
  auxiliary context rather than transcript truth
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

from orbit.memory.backend import ApplicationMemoryRetrievalBackend, MemoryRetrievalBackend, PostgresMemoryRetrievalBackend
from orbit.memory.embedding_service import EmbeddingService
from orbit.memory.extraction import extract_durable_candidates
from orbit.memory.retrieval import default_retrieval_backend_plan
from orbit.models import (
    ConversationMessage,
    MemoryEmbedding,
    MemoryRecord,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
)
from orbit.runtime.execution.context_assembly import ContextFragment
from orbit.settings import DEFAULT_MEMORY_RETRIEVAL_TOP_K
from orbit.store.base import OrbitStore


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokenize(value: str) -> set[str]:
    return set(part for part in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if part)


class MemoryService:
    """Provide bounded first-slice memory extraction and retrieval."""

    def __init__(self, *, store: OrbitStore, embedding_service: EmbeddingService | None = None, retrieval_backend: MemoryRetrievalBackend | None = None):
        self.store = store
        self.embedding_service = embedding_service or EmbeddingService()
        self.retrieval_backend = retrieval_backend or self._select_retrieval_backend()

    def _select_retrieval_backend(self) -> MemoryRetrievalBackend:
        """Select the current retrieval backend based on active store type."""
        store_name = self.store.__class__.__name__.lower()
        if "postgres" in store_name:
            return PostgresMemoryRetrievalBackend()
        return ApplicationMemoryRetrievalBackend()

    def capture_turn_memory(
        self,
        *,
        session_id: str,
        run_id: str,
        user_message: ConversationMessage | None,
        assistant_message: ConversationMessage | None,
    ) -> list[MemoryRecord]:
        """Persist bounded session and durable memory candidates for one turn."""
        if user_message is None and assistant_message is None:
            return []
        persisted: list[MemoryRecord] = []
        parts: list[str] = []
        if user_message is not None and user_message.content.strip():
            parts.append(f"User: {user_message.content.strip()}")
        if assistant_message is not None and assistant_message.content.strip():
            parts.append(f"Assistant: {assistant_message.content.strip()}")
        if parts:
            summary = " | ".join(parts)
            session_record = MemoryRecord(
                scope=MemoryScope.SESSION,
                memory_type=MemoryType.SUMMARY,
                source_kind=MemorySourceKind.DERIVED_SUMMARY,
                session_id=session_id,
                run_id=run_id,
                source_message_id=assistant_message.message_id if assistant_message is not None else user_message.message_id if user_message is not None else None,
                summary_text=summary[:500],
                detail_text="\n\n".join(parts),
                tags=["session_turn", "summary"],
                salience=0.4,
                confidence=0.7,
                metadata={
                    "user_message_id": user_message.message_id if user_message is not None else None,
                    "assistant_message_id": assistant_message.message_id if assistant_message is not None else None,
                },
            )
            self.store.save_memory_record(session_record)
            self._upsert_embedding_for_record(session_record)
            persisted.append(session_record)
        persisted.extend(
            self._promote_durable_memories(
                session_id=session_id,
                run_id=run_id,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        )
        return persisted

    def _upsert_embedding_for_record(self, record: MemoryRecord) -> MemoryEmbedding:
        """Create and persist the current embedding row for one memory record."""
        canonical_text = self.embedding_service.build_memory_text(record)
        content_sha1 = hashlib.sha1(canonical_text.encode("utf-8")).hexdigest()
        existing_rows = self.store.list_memory_embeddings(memory_id=record.memory_id, model_name=self.embedding_service.model_name)
        for existing in existing_rows:
            if existing.content_sha1 == content_sha1:
                record.metadata["embedding_status"] = "dedupe_hit"
                record.metadata["embedding_content_sha1"] = content_sha1
                return existing
        embedding = self.embedding_service.embed_memory_record(record)
        self.store.save_memory_embedding(embedding)
        record.metadata["embedding_status"] = "refreshed"
        record.metadata["embedding_content_sha1"] = embedding.content_sha1
        return embedding

    def _maybe_make_durable_record(
        self,
        *,
        session_id: str,
        run_id: str,
        source_message_id: str | None,
        memory_type: MemoryType,
        summary_text: str,
        detail_text: str,
        tags: list[str],
        salience: float,
        confidence: float,
    ) -> MemoryRecord | None:
        normalized_summary = _normalize_text(summary_text)
        if not normalized_summary:
            return None
        existing = self.store.list_memory_records(scope="durable", limit=200)
        for record in existing:
            if record.memory_type == memory_type and _normalize_text(record.summary_text) == normalized_summary:
                record.metadata["promotion_dedupe"] = True
                return record
        durable = MemoryRecord(
            scope=MemoryScope.DURABLE,
            memory_type=memory_type,
            source_kind=MemorySourceKind.DERIVED_SUMMARY,
            session_id=session_id,
            run_id=run_id,
            source_message_id=source_message_id,
            summary_text=summary_text[:500],
            detail_text=detail_text,
            tags=tags,
            salience=salience,
            confidence=confidence,
            metadata={"promotion_strategy": "policy_v2", "promotion_dedupe": False},
        )
        self.store.save_memory_record(durable)
        self._upsert_embedding_for_record(durable)
        return durable

    def _promote_durable_memories(
        self,
        *,
        session_id: str,
        run_id: str,
        user_message: ConversationMessage | None,
        assistant_message: ConversationMessage | None,
    ) -> list[MemoryRecord]:
        promoted: list[MemoryRecord] = []
        user_text = user_message.content.strip() if user_message is not None else ""
        assistant_text = assistant_message.content.strip() if assistant_message is not None else ""
        source_message_id = assistant_message.message_id if assistant_message is not None else user_message.message_id if user_message is not None else None

        for candidate in extract_durable_candidates(user_text=user_text, assistant_text=assistant_text):
            record = self._maybe_make_durable_record(
                session_id=session_id,
                run_id=run_id,
                source_message_id=source_message_id,
                memory_type=candidate.memory_type,
                summary_text=candidate.summary_text,
                detail_text=candidate.detail_text,
                tags=candidate.tags,
                salience=candidate.salience,
                confidence=candidate.confidence,
            )
            if record is not None:
                if isinstance(record.metadata, dict):
                    record.metadata.setdefault("promotion_strategy", candidate.strategy)
                promoted.append(record)
        return promoted

    def retrieve_memory_fragments(self, *, session_id: str | None, query_text: str, limit: int = DEFAULT_MEMORY_RETRIEVAL_TOP_K) -> list[ContextFragment]:
        """Return retrieval-oriented context fragments for the current query."""
        if not query_text.strip():
            return []
        candidate_records: list[MemoryRecord] = []
        candidate_records.extend(self.store.list_memory_records(scope="durable", limit=200))
        if session_id is not None:
            candidate_records.extend(self.store.list_memory_records(scope="session", session_id=session_id, limit=200))
        if not candidate_records:
            return []

        embedding_by_memory_id: dict[str, MemoryEmbedding] = {}
        for embedding in self.store.list_memory_embeddings(model_name=self.embedding_service.model_name):
            embedding_by_memory_id.setdefault(embedding.memory_id, embedding)

        backend_plan = default_retrieval_backend_plan()
        backend_plan.backend = getattr(self.retrieval_backend, "backend_name", backend_plan.backend)
        backend_plan.strategy = getattr(self.retrieval_backend, "strategy_name", backend_plan.strategy)
        query_vector = self.embedding_service.embed_text(query_text)
        for record in candidate_records:
            embedding = embedding_by_memory_id.get(record.memory_id)
            if embedding is None:
                embedding = self._upsert_embedding_for_record(record)
                embedding_by_memory_id[record.memory_id] = embedding
        scored = self.retrieval_backend.score(
            query_text=query_text,
            query_vector=query_vector,
            records=candidate_records,
            embeddings=embedding_by_memory_id,
        )

        fragments: list[ContextFragment] = []
        seen_memory_ids: set[str] = set()
        for scored_item in scored:
            hybrid_score = scored_item.hybrid_score
            semantic_score = scored_item.semantic_score
            lexical_score = scored_item.lexical_score
            record = scored_item.memory
            if record.memory_id in seen_memory_ids:
                continue
            seen_memory_ids.add(record.memory_id)
            fragments.append(
                ContextFragment(
                    fragment_name=f"memory:{record.memory_type}:{record.memory_id}",
                    visibility_scope="memory_retrieval",
                    content=record.summary_text if record.summary_text.strip() else record.detail_text,
                    priority=55,
                    metadata={
                        "memory_id": record.memory_id,
                        "memory_scope": record.scope,
                        "memory_type": record.memory_type,
                        "retrieval_mode": "hybrid_embedding_lexical_v1",
                        "query_text": query_text,
                        "score": round(hybrid_score, 6),
                        "semantic_score": round(semantic_score, 6),
                        "lexical_score": round(lexical_score, 6),
                        "embedding_model": self.embedding_service.model_name,
                        "retrieval_backend": backend_plan.backend,
                        "retrieval_strategy": backend_plan.strategy,
                    },
                )
            )
            if len(fragments) >= limit:
                break
        return fragments
