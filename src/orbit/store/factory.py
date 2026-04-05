"""Store factory helpers for ORBIT persistence selection.

This module centralizes persistence backend selection so runtime, CLI, and
notebook code can depend on a stable store boundary rather than backend
construction details.
"""

from __future__ import annotations

from orbit.settings import (
    DEFAULT_DB_PATH,
    DEFAULT_PG_DBNAME,
    DEFAULT_PG_HOST,
    DEFAULT_PG_PASSWORD,
    DEFAULT_PG_PORT,
    DEFAULT_PG_USER,
    DEFAULT_STORE_BACKEND,
)
from orbit.store.base import OrbitStore
from orbit.store.postgres_store import PostgresConfig, PostgresStore
from orbit.store.sqlite_store import SQLiteStore


def _build_postgres_store() -> OrbitStore:
    """Construct the PostgreSQL-backed store from current settings."""
    return PostgresStore(
        PostgresConfig(
            host=DEFAULT_PG_HOST,
            port=DEFAULT_PG_PORT,
            dbname=DEFAULT_PG_DBNAME,
            user=DEFAULT_PG_USER,
            password=DEFAULT_PG_PASSWORD,
        )
    )


def create_default_store() -> OrbitStore:
    """Create the current ORBIT store based on configured backend policy.

    Backend selection rule for the current persistence phase:
    - `postgres` is the intended primary runtime backend.
    - `sqlite` remains the bounded local fallback path.

    If PostgreSQL is selected but not currently reachable, the factory falls
    back to SQLite so local bring-up and notebook work remain possible without
    changing runtime code paths.
    """
    if DEFAULT_STORE_BACKEND == "postgres":
        try:
            return _build_postgres_store()
        except Exception:
            return SQLiteStore(DEFAULT_DB_PATH)
    return SQLiteStore(DEFAULT_DB_PATH)
