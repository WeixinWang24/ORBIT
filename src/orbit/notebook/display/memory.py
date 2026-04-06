"""Notebook DataFrame projection helpers for ORBIT memory artifacts.

These helpers keep the notebook surface aligned with the current first-slice
memory architecture:
- canonical memory records
- derived memory embeddings
- retrieval probe results
- memory-related context artifacts
- retrieval summary/comparison views for showcase notebooks
"""

from __future__ import annotations

import json

import pandas as pd

from orbit.memory import MemoryService
from orbit.store.base import OrbitStore


def memory_records_dataframe(store: OrbitStore, *, session_id: str | None = None, scope: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Return memory records as a notebook-friendly DataFrame."""
    records = store.list_memory_records(session_id=session_id, scope=scope, limit=limit)
    rows = []
    for record in records:
        rows.append(
            {
                "memory_id": record.memory_id,
                "scope": record.scope,
                "memory_type": record.memory_type,
                "source_kind": record.source_kind,
                "session_id": record.session_id,
                "run_id": record.run_id,
                "source_message_id": record.source_message_id,
                "summary_text": record.summary_text,
                "detail_text": record.detail_text,
                "tags": record.tags,
                "salience": record.salience,
                "confidence": record.confidence,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "archived_at": record.archived_at,
                "metadata": record.metadata,
            }
        )
    return pd.DataFrame(rows)


def memory_embeddings_dataframe(store: OrbitStore, *, session_id: str | None = None, model_name: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Return derived memory embeddings as a notebook-friendly DataFrame."""
    records = store.list_memory_records(session_id=session_id, limit=limit) if session_id is not None else []
    memory_ids = {record.memory_id for record in records}
    embeddings = store.list_memory_embeddings(model_name=model_name)
    rows = []
    for embedding in embeddings:
        if memory_ids and embedding.memory_id not in memory_ids:
            continue
        rows.append(
            {
                "embedding_id": embedding.embedding_id,
                "memory_id": embedding.memory_id,
                "model_name": embedding.model_name,
                "embedding_dim": embedding.embedding_dim,
                "content_sha1": embedding.content_sha1,
                "created_at": embedding.created_at,
                "metadata": embedding.metadata,
            }
        )
    return pd.DataFrame(rows)


def memory_probe_dataframe(
    store: OrbitStore,
    *,
    session_id: str | None,
    query_text: str,
    limit: int = 5,
    scope: str = "all",
    memory_service: MemoryService | None = None,
    backend_override: str | None = None,
) -> pd.DataFrame:
    """Return structured retrieval probe results as a DataFrame."""
    service = memory_service or MemoryService(store=store)
    probe = service.probe_memory_retrieval(
        session_id=session_id,
        query_text=query_text,
        limit=limit,
        scope=scope,
        backend_override=backend_override,
    )
    rows = []
    for result in probe.get("results", []):
        rows.append(
            {
                "memory_id": result.get("memory_id"),
                "memory_scope": result.get("memory_scope"),
                "memory_type": result.get("memory_type"),
                "summary_text": result.get("summary_text"),
                "score": result.get("score"),
                "semantic_score": result.get("semantic_score"),
                "lexical_score": result.get("lexical_score"),
                "durable_boost": result.get("durable_boost"),
                "session_boost": result.get("session_boost"),
                "salience_bonus": result.get("salience_bonus"),
                "embedding_model": result.get("embedding_model"),
                "retrieval_backend": result.get("retrieval_backend"),
                "retrieval_strategy": result.get("retrieval_strategy"),
                "promotion_strategy": result.get("promotion_strategy"),
            }
        )
    return pd.DataFrame(rows)


def memory_context_artifacts_dataframe(store: OrbitStore, run_id: str, *, artifact_type: str | None = None) -> pd.DataFrame:
    """Return memory-related context artifacts for notebook inspection."""
    artifacts = store.list_context_for_run(run_id)
    rows = []
    for artifact in artifacts:
        if artifact_type is not None and artifact.artifact_type != artifact_type:
            continue
        parsed_content = None
        try:
            parsed_content = json.loads(artifact.content)
        except Exception:
            parsed_content = artifact.content
        rows.append(
            {
                "context_artifact_id": artifact.context_artifact_id,
                "run_id": artifact.run_id,
                "artifact_type": artifact.artifact_type,
                "source": artifact.source,
                "created_at": artifact.created_at,
                "content": parsed_content,
            }
        )
    return pd.DataFrame(rows)


def memory_scope_summary_dataframe(store: OrbitStore, *, session_id: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Return a compact scope/type summary for current memory records."""
    df = memory_records_dataframe(store, session_id=session_id, limit=limit)
    if df.empty:
        return pd.DataFrame(columns=["scope", "memory_type", "count", "avg_salience", "avg_confidence"])
    summary = (
        df.groupby(["scope", "memory_type"])
        .agg(
            count=("memory_id", "count"),
            avg_salience=("salience", "mean"),
            avg_confidence=("confidence", "mean"),
        )
        .reset_index()
        .sort_values(by=["scope", "count", "memory_type"], ascending=[True, False, True])
        .reset_index(drop=True)
    )
    return summary


def memory_compare_backends_dataframe(
    store: OrbitStore,
    *,
    session_id: str | None,
    query_text: str,
    limit: int = 5,
    scope: str = "all",
    memory_service: MemoryService | None = None,
) -> pd.DataFrame:
    """Return a backend-compare summary for application vs postgres probe paths."""
    service = memory_service or MemoryService(store=store)
    application = service.probe_memory_retrieval(
        session_id=session_id,
        query_text=query_text,
        limit=limit,
        scope=scope,
        backend_override="application",
    )
    postgres = service.probe_memory_retrieval(
        session_id=session_id,
        query_text=query_text,
        limit=limit,
        scope=scope,
        backend_override="postgres",
    )
    app_results = {item.get("memory_id"): item for item in application.get("results", [])}
    pg_results = {item.get("memory_id"): item for item in postgres.get("results", [])}
    ordered_ids = []
    for result in application.get("results", []):
        memory_id = result.get("memory_id")
        if memory_id and memory_id not in ordered_ids:
            ordered_ids.append(memory_id)
    for result in postgres.get("results", []):
        memory_id = result.get("memory_id")
        if memory_id and memory_id not in ordered_ids:
            ordered_ids.append(memory_id)
    rows = []
    for memory_id in ordered_ids:
        app = app_results.get(memory_id, {})
        pg = pg_results.get(memory_id, {})
        rows.append(
            {
                "memory_id": memory_id,
                "summary_text": app.get("summary_text") or pg.get("summary_text"),
                "application_score": app.get("score"),
                "postgres_score": pg.get("score"),
                "delta": round((app.get("score") or 0.0) - (pg.get("score") or 0.0), 6),
                "application_strategy": app.get("retrieval_strategy"),
                "postgres_strategy": pg.get("retrieval_strategy"),
            }
        )
    return pd.DataFrame(rows)


def memory_status_summary_frame(summary: dict) -> pd.DataFrame:
    """Render a compact one-row status card from a memory summary bundle."""
    status = summary.get("status", {}) if isinstance(summary, dict) else {}
    posture = summary.get("current_backend_posture", {}) if isinstance(summary, dict) else {}
    return pd.DataFrame([
        {
            "session_id": summary.get("session_id"),
            "run_id": summary.get("run_id"),
            "record_count": summary.get("record_count"),
            "durable_record_count": summary.get("durable_record_count"),
            "embedding_count": summary.get("embedding_count"),
            "probe_result_count": summary.get("probe_result_count"),
            "probe_artifact_count": summary.get("probe_artifact_count"),
            "retrieval_readiness": summary.get("retrieval_readiness"),
            "has_durable_memory": summary.get("has_durable_memory"),
            "has_embeddings": summary.get("has_embeddings"),
            "has_probe_artifacts": summary.get("has_probe_artifacts"),
            "dominant_memory_types": ", ".join(summary.get("dominant_memory_types", [])),
            "embedding_models": ", ".join(summary.get("embedding_models", [])),
            "backend_mode": status.get("backend_mode", posture.get("default_backend")),
            "backend_strategy": status.get("backend_strategy", posture.get("default_strategy")),
            "postgres_mode": status.get("postgres_mode"),
            "memory_layer": status.get("memory_layer"),
            "retrieval_layer": status.get("retrieval_layer"),
            "artifact_layer": status.get("artifact_layer"),
        }
    ])
