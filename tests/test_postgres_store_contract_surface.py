from __future__ import annotations

from orbit.store.postgres_store import PostgresStore


def test_postgres_store_exposes_required_contract_methods():
    required = [
        "save_managed_process",
        "list_managed_processes",
        "get_managed_process",
        "delete_session",
        "delete_all_sessions",
        "list_tool_invocations_for_run",
    ]

    for name in required:
        assert hasattr(PostgresStore, name), f"missing PostgresStore method: {name}"
