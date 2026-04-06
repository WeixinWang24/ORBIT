from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService
from orbit.notebook.providers.memory_demo import memory_showcase_summary_frames
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.notebook import (
    memory_compare_backends_dataframe,
    memory_context_artifacts_dataframe,
    memory_embeddings_dataframe,
    memory_probe_dataframe,
    memory_records_dataframe,
    memory_scope_summary_dataframe,
    memory_status_summary_frame,
)
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-notebook-memory"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "concise" in lowered else 0.0,
            1.0 if "orbit" in lowered else 0.0,
            1.0 if "decision" in lowered or "durable" in lowered else 0.0,
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


def test_notebook_memory_dataframes_cover_records_embeddings_probes_and_artifacts(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    store.save_session(
        ConversationSession(
            session_id="session_1",
            conversation_id="run_1",
            backend_name="openai-codex",
            model="gpt-5.4",
            status="active",
        )
    )
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService())

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise ORBIT answers.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: durable memory should stay inspectable.", turn_index=2)
    store.save_message(user)
    store.save_message(assistant)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)
    service.probe_memory_retrieval(session_id="session_1", query_text="concise durable orbit", limit=5, scope="all")

    records_df = memory_records_dataframe(store, session_id="session_1")
    embeddings_df = memory_embeddings_dataframe(store, session_id="session_1", model_name="fake-notebook-memory")
    probe_df = memory_probe_dataframe(
        store,
        session_id="session_1",
        query_text="concise durable orbit",
        limit=5,
        scope="all",
        memory_service=service,
    )
    scope_summary_df = memory_scope_summary_dataframe(store, session_id="session_1")
    compare_df = memory_compare_backends_dataframe(
        store,
        session_id="session_1",
        query_text="concise durable orbit",
        limit=5,
        scope="all",
        memory_service=service,
    )
    artifacts_df = memory_context_artifacts_dataframe(store, "run_1", artifact_type="memory_probe_snapshot")
    summary_bundle = memory_showcase_summary_frames(
        store=store,
        service=service,
        session=store.get_session("session_1"),
        query_text="concise durable orbit",
    )
    status_df = memory_status_summary_frame(summary_bundle["summary"])

    assert not records_df.empty
    assert "memory_type" in records_df.columns
    assert not embeddings_df.empty
    assert "embedding_dim" in embeddings_df.columns
    assert not probe_df.empty
    assert "retrieval_strategy" in probe_df.columns
    assert not scope_summary_df.empty
    assert "avg_salience" in scope_summary_df.columns
    assert not compare_df.empty
    assert "application_score" in compare_df.columns
    assert not artifacts_df.empty
    assert "artifact_type" in artifacts_df.columns
    assert not status_df.empty
    assert "retrieval_readiness" in status_df.columns
