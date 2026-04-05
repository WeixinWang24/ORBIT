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

from orbit.models import (
    ConversationMessage,
    MemoryEmbedding,
    MemoryRecord,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
)
from orbit.runtime.embedding_service import EmbeddingService, cosine_similarity
from orbit.runtime.execution.context_assembly import ContextFragment
from orbit.settings import DEFAULT_MEMORY_RETRIEVAL_TOP_K
from orbit.store.base import OrbitStore


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokenize(value: str) -> set[str]:
    return set(part for part in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if part)


class MemoryService:
    """Provide bounded first-slice memory extraction and retrieval."""

    def __init__(self, *, store: OrbitStore, embedding_service: EmbeddingService | None = None):
        self.store = store
        self.embedding_service = embedding_service or EmbeddingService()

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
                return existing
        embedding = self.embedding_service.embed_memory_record(record)
        self.store.save_memory_embedding(embedding)
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
            metadata={"promotion_strategy": "rule_based_v1"},
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

        if user_text:
            lowered = user_text.lower()
            if "i prefer" in lowered or "prefer " in lowered:
                record = self._maybe_make_durable_record(
                    session_id=session_id,
                    run_id=run_id,
                    source_message_id=source_message_id,
                    memory_type=MemoryType.USER_PREFERENCE,
                    summary_text=user_text,
                    detail_text=user_text,
                    tags=["user_preference", "rule_based"],
                    salience=0.8,
                    confidence=0.75,
                )
                if record is not None:
                    promoted.append(record)
            if "todo" in lowered or "remember to" in lowered or "need to" in lowered:
                record = self._maybe_make_durable_record(
                    session_id=session_id,
                    run_id=run_id,
                    source_message_id=source_message_id,
                    memory_type=MemoryType.TODO,
                    summary_text=user_text,
                    detail_text=user_text,
                    tags=["todo", "rule_based"],
                    salience=0.85,
                    confidence=0.7,
                )
                if record is not None:
                    promoted.append(record)

        candidate_text = assistant_text or user_text
        lowered_candidate = candidate_text.lower()
        if candidate_text:
            if "decided" in lowered_candidate or "decision" in lowered_candidate or "we will" in lowered_candidate:
                record = self._maybe_make_durable_record(
                    session_id=session_id,
                    run_id=run_id,
                    source_message_id=source_message_id,
                    memory_type=MemoryType.DECISION,
                    summary_text=candidate_text,
                    detail_text=candidate_text,
                    tags=["decision", "rule_based"],
                    salience=0.9,
                    confidence=0.72,
                )
                if record is not None:
                    promoted.append(record)
            if "lesson" in lowered_candidate or "rule of thumb" in lowered_candidate or "remember:" in lowered_candidate:
                record = self._maybe_make_durable_record(
                    session_id=session_id,
                    run_id=run_id,
                    source_message_id=source_message_id,
                    memory_type=MemoryType.LESSON,
                    summary_text=candidate_text,
                    detail_text=candidate_text,
                    tags=["lesson", "rule_based"],
                    salience=0.75,
                    confidence=0.68,
                )
                if record is not None:
                    promoted.append(record)
        return promoted

    def retrieve_memory_fragments(self, *, session_id: str | None, query_text: str, limit: int = DEFAULT_MEMORY_RETRIEVAL_TOP_K) -> list[ContextFragment]:
        """Return retrieval-oriented context fragments for the current query.

        Current first slice uses recent durable memory first, then session memory,
        as a non-embedding placeholder retrieval strategy. The interface shape is
        chosen so later embedding-backed retrieval can replace the selection
        logic without changing context-assembly consumers.
        """
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

        query_vector = self.embedding_service.embed_text(query_text)
        query_tokens = _tokenize(query_text)
        scored: list[tuple[float, float, float, MemoryRecord]] = []
        for record in candidate_records:
            embedding = embedding_by_memory_id.get(record.memory_id)
            if embedding is None:
                embedding = self._upsert_embedding_for_record(record)
                embedding_by_memory_id[record.memory_id] = embedding
            semantic_score = cosine_similarity(query_vector, embedding.vector)
            lexical_tokens = _tokenize(record.summary_text + "\n" + record.detail_text + "\n" + " ".join(record.tags))
            lexical_score = (len(query_tokens & lexical_tokens) / len(query_tokens)) if query_tokens else 0.0
            hybrid_score = 0.8 * semantic_score + 0.2 * lexical_score
            if hybrid_score <= 0:
                continue
            scored.append((hybrid_score, semantic_score, lexical_score, record))
        scored.sort(key=lambda item: item[0], reverse=True)

        fragments: list[ContextFragment] = []
        seen_memory_ids: set[str] = set()
        for hybrid_score, semantic_score, lexical_score, record in scored:
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
                    },
                )
            )
            if len(fragments) >= limit:
                break
        return fragments
