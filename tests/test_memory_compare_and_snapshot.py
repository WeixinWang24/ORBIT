from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService
from orbit.models import ConversationMessage, MessageRole
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-compare"

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


def test_probe_returns_snapshot_payload(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should rank highly.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    probe = service.probe_memory_retrieval(session_id="session_1", query_text="durable", limit=5, scope="all")
    assert "snapshot" in probe
    assert probe["snapshot"]["query_text"] == "durable"


def test_backend_plan_can_probe_pgvector_when_conn_available(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    store.__class__.__name__ = "PostgresStore"

    class _Cursor:
        def execute(self, *_args, **_kwargs):
            return None
        def fetchone(self):
            return (1,)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    class _Conn:
        def cursor(self):
            return _Cursor()

    store.conn = _Conn()
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    plan = service._current_backend_plan(backend_override="postgres")
    assert plan.capabilities["pgvector_checked"] is True
    assert plan.capabilities["pgvector_available"] is True
