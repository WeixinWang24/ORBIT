from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService, PostgresMemoryRetrievalBackend, extract_durable_candidates
from orbit.store.sqlite_store import SQLiteStore


class _FakePostgresStore(SQLiteStore):
    pass

_FakePostgresStore.__name__ = "PostgresStore"


def test_memory_service_selects_postgres_backend_by_store_name(tmp_path):
    store = _FakePostgresStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store)
    assert isinstance(service.retrieval_backend, PostgresMemoryRetrievalBackend)


def test_policy_v2_2_cleans_summary_prefixes():
    candidates = extract_durable_candidates(
        user_text="I prefer concise answers.",
        assistant_text="Decision: the plan is to keep transcript and memory separated. Remember: keep retrieval inspectable.",
    )
    summaries = [candidate.summary_text for candidate in candidates]
    assert all(not summary.lower().startswith("decision:") for summary in summaries)
    assert all(not summary.lower().startswith("remember:") for summary in summaries)
