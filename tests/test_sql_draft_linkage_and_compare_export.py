from __future__ import annotations

from pathlib import Path

from orbit.memory import PostgresMemoryRetrievalBackend


def test_postgres_backend_exposes_sql_draft_path():
    assert PostgresMemoryRetrievalBackend.sql_draft_path == 'docs/persistence/sql/pgvector-memory-embedding-vectors.sql'


def test_sql_draft_path_exists_on_disk():
    path = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/sql/pgvector-memory-embedding-vectors.sql')
    assert path.exists()
