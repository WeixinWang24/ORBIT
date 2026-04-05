from __future__ import annotations

from pathlib import Path


def test_pgvector_implementation_notes_exist():
    path = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/pgvector-derived-table-implementation-notes.md')
    assert path.exists()


def test_pgvector_implementation_notes_reference_memory_embedding_vectors():
    text = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/docs/persistence/pgvector-derived-table-implementation-notes.md').read_text()
    assert 'memory_embedding_vectors' in text
