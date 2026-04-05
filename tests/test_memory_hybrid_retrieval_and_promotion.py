from __future__ import annotations

from pathlib import Path

from orbit.models import ConversationMessage, MessageRole, MemoryType
from orbit.runtime.memory_service import MemoryService
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-hybrid"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "prefer" in lowered or "concise" in lowered else 0.0,
            1.0 if "todo" in lowered or "remember" in lowered else 0.0,
            1.0 if "decision" in lowered or "we will" in lowered else 0.0,
        ]

    def build_memory_text(self, record):
        return f"{record.summary_text}\n{record.detail_text}\n{' '.join(record.tags)}"

    def embed_memory_record(self, record):
        from orbit.models import MemoryEmbedding

        text = self.build_memory_text(record)
        vector = self.embed_text(text)
        return MemoryEmbedding(
            memory_id=record.memory_id,
            model_name=self.model_name,
            embedding_dim=len(vector),
            content_sha1=str(abs(hash(text))),
            vector=vector,
            metadata={},
        )


def test_rule_based_durable_memory_promotion_and_embedding_dedupe(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise ORBIT architecture answers and remember to ship the transcript store.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: we will keep transcript and memory separated.", turn_index=2)

    first = service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    second = service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    durable = store.list_memory_records(scope="durable", limit=20)
    kinds = {record.memory_type for record in durable}
    assert MemoryType.USER_PREFERENCE in kinds
    assert MemoryType.TODO in kinds
    assert MemoryType.DECISION in kinds

    embeddings = store.list_memory_embeddings(model_name="fake-hybrid")
    unique_pairs = {(embedding.memory_id, embedding.content_sha1) for embedding in embeddings}
    assert len(embeddings) == len(unique_pairs)
    assert len(second) >= len(first)


def test_hybrid_retrieval_exposes_semantic_and_lexical_scores(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: we will keep ORBIT concise.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    fragments = service.retrieve_memory_fragments(session_id="session_1", query_text="concise preference decision", limit=5)
    assert fragments
    assert fragments[0].metadata["retrieval_mode"] == "hybrid_embedding_lexical_v1"
    assert "semantic_score" in fragments[0].metadata
    assert "lexical_score" in fragments[0].metadata
