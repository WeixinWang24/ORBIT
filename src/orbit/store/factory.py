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


def create_default_store() -> OrbitStore:
    """Create the current ORBIT store based on configured backend policy.

    Backend selection rule:
    - `sqlite` keeps the existing bootstrap local bring-up path.
    - `postgres` activates the first real PostgreSQL-backed implementation.

    The default remains SQLite until PostgreSQL is available in the local
    development environment, but the factory now provides a clean switch point.
    """
    if DEFAULT_STORE_BACKEND == "postgres":
        return PostgresStore(
            PostgresConfig(
                host=DEFAULT_PG_HOST,
                port=DEFAULT_PG_PORT,
                dbname=DEFAULT_PG_DBNAME,
                user=DEFAULT_PG_USER,
                password=DEFAULT_PG_PASSWORD,
            )
        )
    return SQLiteStore(DEFAULT_DB_PATH)
