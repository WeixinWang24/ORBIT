"""Notebook helpers for ORBIT memory-system showcase flows.

These helpers provide a compact, inspectable setup layer for memory notebooks so
future showcase notebooks do not need to re-implement the same deterministic
store/bootstrap/capture scaffolding repeatedly.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.memory import MemoryRetrievalWeights, MemoryService
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.notebook.display.memory import memory_compare_backends_dataframe, memory_context_artifacts_dataframe, memory_embeddings_dataframe, memory_probe_dataframe, memory_records_dataframe, memory_scope_summary_dataframe
from orbit.store.sqlite_store import SQLiteStore


class DemoMemoryEmbeddingService:
    """Deterministic embedding stub for notebook memory showcases."""

    model_name = "demo-memory-showcase"

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "concise" in lowered or "preference" in lowered else 0.0,
            1.0 if "orbit" in lowered or "architecture" in lowered else 0.0,
            1.0 if "todo" in lowered or "remember" in lowered or "ship" in lowered else 0.0,
            1.0 if "decision" in lowered or "separate" in lowered or "lesson" in lowered else 0.0,
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


def create_memory_showcase_bundle(*, db_path: Path | None = None, session_id: str = "session_memory_showcase", run_id: str = "run_memory_showcase") -> dict[str, object]:
    """Create a deterministic store/session/service bundle for memory notebooks.

    By default, the showcase database now lives inside the ORBIT repo `.tmp`
    tree so repeated notebook runs stay visible and easy to clean.
    """
    default_db_dir = Path(__file__).resolve().parents[4] / ".tmp" / "notebooks" / "memory_showcase"
    default_db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_path or (default_db_dir / 'orbit.db')
    db_path.unlink(missing_ok=True)
    store = SQLiteStore(db_path=db_path)
    service = MemoryService(store=store, embedding_service=DemoMemoryEmbeddingService())
    session = ConversationSession(
        session_id=session_id,
        conversation_id=run_id,
        backend_name="showcase",
        model="demo-model",
    )
    store.save_session(session)
    return {
        "db_path": db_path,
        "store": store,
        "service": service,
        "session": session,
    }


def default_memory_showcase_turns(session_id: str) -> list[tuple[ConversationMessage, ConversationMessage]]:
    """Return the default two-turn memory showcase dataset."""
    return [
        (
            ConversationMessage(
                session_id=session_id,
                role=MessageRole.USER,
                content="I prefer concise ORBIT architecture answers and remember to ship the transcript store.",
                turn_index=1,
            ),
            ConversationMessage(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content="Decision: the plan is to keep transcript and memory separated.",
                turn_index=2,
            ),
        ),
        (
            ConversationMessage(
                session_id=session_id,
                role=MessageRole.USER,
                content="I also like memory probes that stay inspectable in the notebook.",
                turn_index=3,
            ),
            ConversationMessage(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content="Lesson: keep retrieval results visible as auxiliary context rather than hidden transcript rewrites.",
                turn_index=4,
            ),
        ),
    ]


def capture_memory_showcase_turns(*, store: SQLiteStore, service: MemoryService, session: ConversationSession, turns: list[tuple[ConversationMessage, ConversationMessage]] | None = None) -> list[object]:
    """Persist the default showcase turns into transcript + memory state."""
    turns = turns or default_memory_showcase_turns(session.session_id)
    captured = []
    for user_message, assistant_message in turns:
        store.save_message(user_message)
        store.save_message(assistant_message)
        captured.extend(
            service.capture_turn_memory(
                session_id=session.session_id,
                run_id=session.conversation_id,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        )
    return captured


def build_durable_bias_service(*, store: SQLiteStore) -> MemoryService:
    """Return a showcase service variant that strongly favors durable memory."""
    return MemoryService(
        store=store,
        embedding_service=DemoMemoryEmbeddingService(),
        retrieval_weights=MemoryRetrievalWeights(
            semantic_weight=0.3,
            lexical_weight=0.1,
            durable_boost=1.0,
            session_boost=0.0,
            salience_weight=0.0,
        ),
    )


def memory_showcase_summary_frames(*, store: SQLiteStore, service: MemoryService, session: ConversationSession, query_text: str) -> dict[str, object]:
    """Return the core notebook-facing memory bundle.

    The bundle intentionally mixes:
    - one top-level structured summary dict (`summary`)
    - multiple notebook-facing DataFrames for drill-down views
    """
    records = memory_records_dataframe(store, session_id=session.session_id, limit=50)
    scope_summary = memory_scope_summary_dataframe(store, session_id=session.session_id, limit=50)
    embeddings = memory_embeddings_dataframe(store, session_id=session.session_id)
    probe = memory_probe_dataframe(
        store,
        session_id=session.session_id,
        query_text=query_text,
        limit=10,
        scope="all",
        memory_service=service,
    )
    compare = memory_compare_backends_dataframe(
        store,
        session_id=session.session_id,
        query_text=query_text,
        limit=10,
        scope="all",
        memory_service=service,
    )
    artifacts = memory_context_artifacts_dataframe(store, session.conversation_id, artifact_type="memory_probe_snapshot")
    memory_types = sorted(records["memory_type"].dropna().astype(str).unique().tolist()) if not records.empty and "memory_type" in records.columns else []
    embedding_models = sorted(embeddings["model_name"].dropna().astype(str).unique().tolist()) if not embeddings.empty and "model_name" in embeddings.columns else []
    scope_counts = {
        "session": int((records["scope"] == "session").sum()) if not records.empty and "scope" in records.columns else 0,
        "durable": int((records["scope"] == "durable").sum()) if not records.empty and "scope" in records.columns else 0,
    }
    dominant_memory_types = (
        records["memory_type"].astype(str).value_counts().head(3).index.tolist()
        if not records.empty and "memory_type" in records.columns
        else []
    )
    current_backend_posture = {
        "default_backend": getattr(service.retrieval_backend, "backend_name", "unknown"),
        "default_strategy": getattr(service.retrieval_backend, "strategy_name", "unknown"),
        "compare_supports_postgres_stub": True,
        "postgres_execution_enabled": False,
    }
    summary = {
        "session_id": session.session_id,
        "run_id": session.conversation_id,
        "query_text": query_text,
        "record_count": len(records.index),
        "session_record_count": scope_counts["session"],
        "durable_record_count": scope_counts["durable"],
        "embedding_count": len(embeddings.index),
        "probe_result_count": len(probe.index),
        "compare_row_count": len(compare.index),
        "probe_artifact_count": len(artifacts.index),
        "memory_types": memory_types,
        "embedding_models": embedding_models,
        "dominant_memory_types": dominant_memory_types,
        "has_durable_memory": scope_counts["durable"] > 0,
        "has_probe_artifacts": len(artifacts.index) > 0,
        "has_embeddings": len(embeddings.index) > 0,
        "retrieval_readiness": "ready" if len(records.index) > 0 and len(embeddings.index) > 0 else "partial" if len(records.index) > 0 else "empty",
        "current_backend_posture": current_backend_posture,
        "status": {
            "memory_layer": "active" if len(records.index) > 0 else "empty",
            "retrieval_layer": "inspectable" if len(probe.index) > 0 else "not_yet_observed",
            "artifact_layer": "captured" if len(artifacts.index) > 0 else "not_yet_captured",
            "backend_mode": current_backend_posture["default_backend"],
            "backend_strategy": current_backend_posture["default_strategy"],
            "postgres_mode": "stub_compare_only",
        },
    }
    return {
        "summary": summary,
        "records": records,
        "scope_summary": scope_summary,
        "embeddings": embeddings,
        "probe": probe,
        "compare": compare,
        "artifacts": artifacts,
    }
