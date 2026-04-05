from __future__ import annotations

import json
from pathlib import Path

from orbit.memory import MemoryService, PostgresMemoryRetrievalBackend
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-delta"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [1.0 if "durable" in lowered else 0.0, 1.0 if "session" in lowered else 0.0]

    def build_memory_text(self, record):
        return f"{record.summary_text}\n{record.detail_text}"

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


def test_probe_snapshot_artifact_content_is_json(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    store.save_session(ConversationSession(session_id="session_1", conversation_id="run_1", backend_name="openai-codex", model="gpt-5.4", status="active"))
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should rank highly.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    service.probe_memory_retrieval(session_id="session_1", query_text="durable", limit=5, scope="all")
    artifacts = store.list_context_for_run("run_1")
    snapshot_artifact = next(artifact for artifact in artifacts if artifact.artifact_type == "memory_probe_snapshot")
    parsed = json.loads(snapshot_artifact.content)
    assert parsed["snapshot"]["query_text"] == "durable"


def test_postgres_backend_has_execution_method_stub():
    backend = PostgresMemoryRetrievalBackend()
    assert hasattr(backend, "_score_with_pgvector")
