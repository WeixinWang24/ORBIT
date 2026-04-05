from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService
from orbit.models import ConversationMessage, MessageRole
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-snapshot"

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


def test_probe_snapshot_persists_context_artifact_when_session_exists(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    session = store.save_session
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should rank highly.", turn_index=2)
    from orbit.models import ConversationSession
    store.save_session(ConversationSession(session_id="session_1", conversation_id="run_1", backend_name="openai-codex", model="gpt-5.4", status="active"))
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    probe = service.probe_memory_retrieval(session_id="session_1", query_text="durable", limit=5, scope="all")
    assert "context_artifact_id" in probe["snapshot"]
    artifacts = store.list_context_for_run("run_1")
    assert any(artifact.artifact_type == "memory_probe_snapshot" for artifact in artifacts)
