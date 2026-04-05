from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryRetrievalWeights, MemoryService
from orbit.models import ConversationMessage, MessageRole
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-weights"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "durable" in lowered or "decision" in lowered else 0.0,
            1.0 if "session" in lowered or "summary" in lowered else 0.0,
            1.0 if "concise" in lowered else 0.0,
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


def test_probe_and_runtime_retrieval_share_same_path(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: use durable memory for key facts.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    probe = service.probe_memory_retrieval(session_id="session_1", query_text="durable concise", limit=5, scope="all")
    fragments = service.retrieve_memory_fragments(session_id="session_1", query_text="durable concise", limit=5)

    assert probe["results"]
    assert fragments
    assert probe["results"][0]["memory_id"] == fragments[0].metadata["memory_id"]


def test_retrieval_weights_can_bias_scope(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    weights = MemoryRetrievalWeights(durable_boost=0.5, session_boost=0.0)
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService(), retrieval_weights=weights)
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should win ranking.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    probe = service.probe_memory_retrieval(session_id="session_1", query_text="durable concise", limit=5, scope="all")
    assert probe["results"]
    assert probe["backend_plan"].backend == "application"
