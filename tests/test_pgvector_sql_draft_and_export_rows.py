from __future__ import annotations

from pathlib import Path


def test_pgvector_sql_draft_file_exists():
    path = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/sql/pgvector-memory-embedding-vectors.sql')
    assert path.exists()


def test_pgvector_sql_draft_mentions_memory_embedding_vectors():
    text = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/sql/pgvector-memory-embedding-vectors.sql').read_text()
    assert 'memory_embedding_vectors' in text
    assert 'embedding VECTOR(<dim>) NOT NULL' in text
