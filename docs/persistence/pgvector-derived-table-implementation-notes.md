# ORBIT pgvector Derived-Table Implementation Notes

## Purpose

Turn the pgvector derived-table preparation into a more implementation-oriented note.
This file complements:
- `pgvector-derived-table-prep.md`
- `pgvector-migration-prep.md`

## Proposed derived table

Conceptual name:
- `memory_embedding_vectors`

Proposed fields:
- `memory_id TEXT PRIMARY KEY`
- `model_name TEXT NOT NULL`
- `embedding_dim INTEGER NOT NULL`
- `content_sha1 TEXT NOT NULL`
- `scope TEXT NOT NULL`
- `memory_type TEXT NOT NULL`
- `session_id TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `embedding VECTOR(<dim>) NOT NULL`

## Why these fields

- `memory_id` links back to canonical memory
- `model_name` prevents mixed-model ambiguity
- `embedding_dim` guards model/schema mismatch
- `content_sha1` supports dedupe/rebuild checks
- `scope` / `memory_type` / `session_id` support query-time filtering without heavy JSON extraction
- `created_at` helps debug rebuild freshness

## Fill / update policy

Preferred first implementation:
1. compute/update canonical `MemoryEmbedding`
2. mirror it into `memory_embedding_vectors`
3. if `content_sha1` unchanged, skip update
4. if changed, replace/update vector row

## Rebuild policy

A full rebuild should be safe because the derived table is not canonical.
Expected rebuild triggers:
- embedding model changed
- dimension changed
- corrupted vector rows
- migration testing / verification

## Query policy

Initial execution target should be exact similarity, not approximate ANN.
That keeps validation easier during compare-mode bring-up.

Likely starter query pattern:

```sql
SELECT memory_id,
       1 - (embedding <=> $query_vector) AS score
FROM memory_embedding_vectors
WHERE model_name = $model_name
ORDER BY embedding <=> $query_vector
LIMIT $k;
```

## Draft DDL shape

```sql
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
```

SQL draft file:
- `docs/persistence/sql/pgvector-memory-embedding-vectors.sql`

Later optional filters:
- `scope = 'durable'`
- `scope = 'session' AND session_id = $session_id`
- `memory_type = $memory_type`

## Validation rule

Do not switch default execution to pgvector until compare mode shows acceptable agreement against the application backend for representative queries.

## Operational rule

Keep application backend available even after pgvector activation.
It remains the fallback and the comparison baseline.
