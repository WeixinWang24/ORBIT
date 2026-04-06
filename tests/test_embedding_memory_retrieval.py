from __future__ import annotations

from pathlib import Path

from orbit.models import ConversationMessage, MessageRole
from orbit.memory import MemoryService
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-mini"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "concise" in lowered else 0.0,
            1.0 if "orbit" in lowered else 0.0,
            1.0 if "weather" in lowered else 0.0,
        ]

    def build_memory_text(self, record):
        return f"{record.summary_text}\n\n{record.detail_text}".strip()

    def embed_memory_record(self, record):
        from orbit.models import MemoryEmbedding

        vector = self.embed_text(self.build_memory_text(record))
        return MemoryEmbedding(
            memory_id=record.memory_id,
            model_name=self.model_name,
            embedding_dim=len(vector),
            content_sha1="fake",
            vector=vector,
            metadata={},
        )


def test_capture_turn_persists_embedding_and_retrieval_is_semantic(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="remember I prefer concise answers for ORBIT design work", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Got it. I will keep ORBIT replies concise.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    embeddings = store.list_memory_embeddings(model_name="fake-mini")
    assert len(embeddings) >= 1

    fragments = service.retrieve_memory_fragments(session_id="session_1", query_text="what are my concise orbit preferences?", limit=5)
    assert fragments
    assert fragments[0].metadata["retrieval_mode"] == "hybrid_embedding_lexical_v1"
    assert fragments[0].metadata["embedding_model"] == "fake-mini"
    assert "concise" in fragments[0].content.lower()
