from __future__ import annotations

import json
from pathlib import Path

from orbit.memory import MemoryService, PostgresMemoryRetrievalBackend
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-compare-artifact"

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


def test_backend_dry_run_payload_exposes_migration_stub():
    payload = PostgresMemoryRetrievalBackend().dry_run_payload()
    assert payload["migration_stub_path"] == "docs/persistence/sql/migrations/0001_pgvector_memory_embedding_vectors.sql"


def test_compare_summary_artifact_is_persisted(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    store.save_session(ConversationSession(session_id="session_1", conversation_id="run_1", backend_name="openai-codex", model="gpt-5.4", status="active"))
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should rank highly.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    service.probe_memory_retrieval(session_id="session_1", query_text="durable", limit=5, scope="all", backend_override="postgres")
    artifacts = store.list_context_for_run("run_1")
    compare_artifact = next(artifact for artifact in artifacts if artifact.artifact_type == "memory_compare_summary")
    parsed = json.loads(compare_artifact.content)
    assert "export_rows" in parsed


def test_migration_stub_file_exists():
    path = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/sql/migrations/0001_pgvector_memory_embedding_vectors.sql')
    assert path.exists()
