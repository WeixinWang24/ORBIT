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
    MemoryRecord,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
)
from orbit.runtime.execution.context_assembly import ContextFragment
from orbit.store.base import OrbitStore


class MemoryService:
    """Provide bounded first-slice memory extraction and retrieval."""

    def __init__(self, *, store: OrbitStore):
        self.store = store

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
        return [record]

    def retrieve_memory_fragments(self, *, session_id: str | None, query_text: str, limit: int = 5) -> list[ContextFragment]:
        """Return retrieval-oriented context fragments for the current query.

        Current first slice uses recent durable memory first, then session memory,
        as a non-embedding placeholder retrieval strategy. The interface shape is
        chosen so later embedding-backed retrieval can replace the selection
        logic without changing context-assembly consumers.
        """
        if not query_text.strip():
            return []
        records: list[MemoryRecord] = []
        records.extend(self.store.list_memory_records(scope="durable", limit=limit))
        if len(records) < limit and session_id is not None:
            remaining = limit - len(records)
            records.extend(self.store.list_memory_records(scope="session", session_id=session_id, limit=remaining))
        fragments: list[ContextFragment] = []
        for record in records[:limit]:
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
                        "retrieval_mode": "pre_embedding_first_slice",
                        "query_text": query_text,
                    },
                )
            )
        return fragments
