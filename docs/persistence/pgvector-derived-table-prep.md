# ORBIT pgvector Derived-Table Prep

## Purpose

Define the likely derived-table shape for enabling pgvector-backed retrieval execution without changing canonical memory ownership.

## Guiding rule

- `memory_records` stays canonical
- `memory_embeddings` stays the portable/rebuildable embedding record store
- a future pgvector table should be treated as a **derived execution table**, not the canonical memory source

## Proposed table

A likely future table shape is something like:

- `memory_id` (PK / FK to canonical memory record)
- `model_name`
- `embedding_dim`
- `content_sha1`
- `embedding VECTOR(<dim>)`
- `created_at`
- optional filter columns:
  - `scope`
  - `memory_type`
  - `session_id`

Suggested conceptual name:
- `memory_embedding_vectors`

## Why a separate derived table

Reasons to prefer a separate derived table over mutating the current JSONB row directly:
- keeps canonical memory storage and execution-optimized vector storage distinct
- allows full rebuild from canonical/portable embedding rows
- makes pgvector-specific migration reversible
- reduces pressure to distort current JSONB-first persistence design

## Fill path

Likely population path:
1. read canonical `memory_records`
2. read/refresh current `memory_embeddings`
3. insert/update matching rows in `memory_embedding_vectors`
4. use `content_sha1` for dedupe / rebuild checks

See implementation-oriented follow-up:
- `docs/persistence/pgvector-derived-table-implementation-notes.md`

## Query shape

Initial exact-similarity shape can remain simple:

```sql
SELECT memory_id,
       1 - (embedding <=> $query_vector) AS score
FROM memory_embedding_vectors
ORDER BY embedding <=> $query_vector
LIMIT $k;
```

Additional filter clauses can later scope to:
- durable vs session
- specific session id
- memory type
- model name

## Migration caution

Do not skip the current compare/inspection loop.
The derived-table path should be introduced while keeping:
- application backend available
- compare mode alive
- probe snapshots persisted
- ranking divergence inspectable

## Non-goal

This table is not meant to replace:
- transcript persistence
- durable memory semantics
- memory extraction policy
- portable embedding record storage

It is only meant to improve retrieval execution.
