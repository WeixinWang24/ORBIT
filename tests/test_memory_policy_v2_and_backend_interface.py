from __future__ import annotations

from pathlib import Path

from orbit.memory import ApplicationMemoryRetrievalBackend, MemoryService, extract_durable_candidates
from orbit.models import ConversationMessage, MessageRole, MemoryType
from orbit.store.sqlite_store import SQLiteStore


class _FakeEmbeddingService:
    model_name = "fake-policy-v2"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "prefer" in lowered or "concise" in lowered else 0.0,
            1.0 if "remember" in lowered or "todo" in lowered else 0.0,
            1.0 if "decision" in lowered or "plan" in lowered else 0.0,
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


def test_policy_v2_candidate_extraction_shapes_expected_types():
    candidates = extract_durable_candidates(
        user_text="I prefer concise answers and remember to ship the transcript store.",
        assistant_text="Decision: the plan is to keep transcript and memory separated.",
    )
    kinds = {candidate.memory_type for candidate in candidates}
    assert MemoryType.USER_PREFERENCE in kinds
    assert MemoryType.TODO in kinds
    assert MemoryType.DECISION in kinds


def test_memory_service_uses_backend_interface_and_sets_diagnostics(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    backend = ApplicationMemoryRetrievalBackend()
    service = MemoryService(store=store, embedding_service=_FakeEmbeddingService(), retrieval_backend=backend)

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="I prefer concise ORBIT answers and remember to verify embeddings.", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Decision: the plan is to keep transcript separate from memory.", turn_index=2)
    records = service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    assert any((record.metadata or {}).get("embedding_status") in {"refreshed", "dedupe_hit"} for record in records)
    durable = store.list_memory_records(scope="durable", limit=20)
    assert any((record.metadata or {}).get("promotion_strategy") for record in durable)

    fragments = service.retrieve_memory_fragments(session_id="session_1", query_text="concise plan", limit=5)
    assert fragments
    assert fragments[0].metadata["retrieval_backend"] == "application"
