"""Memory extraction and retrieval helpers for ORBIT first-slice persistence.

This module keeps the first implementation intentionally small:
- derive bounded memory records from transcript-visible session turns
- expose a retrieval shape that can later be upgraded to embedding-backed RAG
- preserve the boundary that retrieved memory enters prompt assembly as
  auxiliary context rather than transcript truth
"""

from __future__ import annotations

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
        """Persist a compact per-turn summary memory when possible.

        Current first slice:
        - one session-scoped summary memory per completed user/assistant pair
        - no autonomous semantic classification yet
        - durable memory promotion is intentionally deferred
        """
        if user_message is None and assistant_message is None:
            return []
        parts: list[str] = []
        if user_message is not None and user_message.content.strip():
            parts.append(f"User: {user_message.content.strip()}")
        if assistant_message is not None and assistant_message.content.strip():
            parts.append(f"Assistant: {assistant_message.content.strip()}")
        if not parts:
            return []
        summary = " | ".join(parts)
        record = MemoryRecord(
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
        self.store.save_memory_record(record)
        self._upsert_embedding_for_record(record)
        return [record]

    def _upsert_embedding_for_record(self, record: MemoryRecord) -> MemoryEmbedding:
        """Create and persist the current embedding row for one memory record."""
        embedding = self.embedding_service.embed_memory_record(record)
        self.store.save_memory_embedding(embedding)
        return embedding

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
        scored: list[tuple[float, MemoryRecord]] = []
        for record in candidate_records:
            embedding = embedding_by_memory_id.get(record.memory_id)
            if embedding is None:
                embedding = self._upsert_embedding_for_record(record)
                embedding_by_memory_id[record.memory_id] = embedding
            score = cosine_similarity(query_vector, embedding.vector)
            if score <= 0:
                continue
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)

        fragments: list[ContextFragment] = []
        seen_memory_ids: set[str] = set()
        for score, record in scored:
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
                        "retrieval_mode": "local_embedding_cosine_v1",
                        "query_text": query_text,
                        "score": round(score, 6),
                        "embedding_model": self.embedding_service.model_name,
                    },
                )
            )
            if len(fragments) >= limit:
                break
        return fragments
