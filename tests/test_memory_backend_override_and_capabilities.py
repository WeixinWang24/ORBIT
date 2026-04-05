from __future__ import annotations

from pathlib import Path

from orbit.memory import MemoryService
from orbit.store.sqlite_store import SQLiteStore


def test_probe_supports_backend_override_to_postgres(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store)
    probe = service.probe_memory_retrieval(session_id=None, query_text="test", limit=5, scope="all", backend_override="postgres")
    assert probe["backend_plan"].backend == "postgres"
    assert probe["backend_plan"].capabilities is not None
    assert probe["backend_plan"].capabilities["execution_enabled"] is False


def test_probe_supports_backend_override_to_application(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store)
    plan = service._current_backend_plan(backend_override="application")
    assert plan.backend == "application"
    assert plan.capabilities is not None
    assert plan.capabilities["execution_enabled"] is True
