from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService, default_memory_retrieval_weights
from orbit.store.sqlite_store import SQLiteStore


def test_default_weights_come_from_settings():
    weights = default_memory_retrieval_weights()
    assert weights.semantic_weight >= 0.0
    assert weights.lexical_weight >= 0.0


class _FakeEmbeddingService:
    model_name = "fake-explain"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [1.0 if "durable" in lowered else 0.0, 1.0 if "concise" in lowered else 0.0]

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


def test_postgres_stub_probe_returns_explainable_payload(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    store.__class__.__name__ = "PostgresStore"
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())
    probe = service.probe_memory_retrieval(session_id=None, query_text="durable concise", limit=5, scope="all")
    assert probe["backend_plan"].backend == "postgres"
    assert "stub" in probe["backend_plan"].notes.lower()
