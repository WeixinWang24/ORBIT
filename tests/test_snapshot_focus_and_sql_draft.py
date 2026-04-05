from __future__ import annotations

from pathlib import Path


def test_pgvector_impl_notes_include_create_table_draft():
    text = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/pgvector-derived-table-implementation-notes.md').read_text()
    assert 'CREATE TABLE IF NOT EXISTS memory_embedding_vectors' in text
    assert 'embedding VECTOR(<dim>) NOT NULL' in text
