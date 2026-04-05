from __future__ import annotations

from orbit.memory import PostgresMemoryRetrievalBackend, extract_durable_candidates
from orbit.models import MemoryType


def test_policy_v2_1_prefers_clause_summary_not_full_message():
    candidates = extract_durable_candidates(
        user_text="I prefer concise answers. Also, we need to ship the transcript store this week.",
        assistant_text="Decision: the plan is to keep transcript and memory separated. Extra context follows here.",
    )
    prefs = [candidate for candidate in candidates if candidate.memory_type == MemoryType.USER_PREFERENCE]
    decisions = [candidate for candidate in candidates if candidate.memory_type == MemoryType.DECISION]
    assert prefs
    assert decisions
    assert prefs[0].summary_text != "I prefer concise answers. Also, we need to ship the transcript store this week."
    assert decisions[0].summary_text != "Decision: the plan is to keep transcript and memory separated. Extra context follows here."


def test_postgres_backend_stub_returns_empty_until_enabled():
    backend = PostgresMemoryRetrievalBackend()
    scores = backend.score(query_text="test", query_vector=[0.1, 0.2], records=[], embeddings={})
    assert scores == []
