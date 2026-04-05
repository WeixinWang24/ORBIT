-- Draft SQL for future pgvector-derived execution table.
-- Canonical memory remains in memory_records; this table is derived execution state.

CREATE TABLE IF NOT EXISTS memory_embedding_vectors (
    memory_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    content_sha1 TEXT NOT NULL,
    scope TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    session_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    embedding VECTOR(<dim>) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_embedding_vectors_model_name
    ON memory_embedding_vectors(model_name);

CREATE INDEX IF NOT EXISTS idx_memory_embedding_vectors_scope_session
    ON memory_embedding_vectors(scope, session_id, memory_type);
