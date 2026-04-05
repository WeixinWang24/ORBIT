# ORBIT pgvector Migration Prep

## Status
Preparation note for moving from the current explainable PostgreSQL retrieval stub to real server-side vector execution.

## What already exists

ORBIT already has the following seams in place:

- PostgreSQL-first canonical persistence for memory rows
- `memory_embeddings` persisted as derivative rows
- retrieval backend interface (`MemoryRetrievalBackend`)
- application retrieval backend as the current real execution path
- PostgreSQL retrieval backend stub with structured capability probe
- inspector compare mode for application vs postgres retrieval planning
- retrieval probe snapshots persisted as context artifacts when a session is available

## Current PostgreSQL status

The current PostgreSQL path can now:
- detect whether a live connection object exists
- probe `pg_extension` for the `vector` extension
- report `pgvector_checked` / `pgvector_available`
- expose this state through backend-plan capabilities and inspector UI

The current PostgreSQL path does **not yet**:
- store vectors in a pgvector-native column
- execute server-side similarity SQL
- rank results from PostgreSQL directly
- enable execution on the postgres retrieval backend

## What must happen next

### 1. Schema evolution
Current schema stores embeddings in JSON payload rows.
To enable efficient pgvector retrieval, ORBIT will likely need either:

- a new pgvector-backed table/column for embeddings, or
- a parallel derived table specifically for retrieval execution

See also:
- `docs/persistence/pgvector-derived-table-prep.md`

Important rule:
- canonical memory rows remain `memory_records`
- embeddings remain derivative and rebuildable
- pgvector schema should be migration-friendly and disposable/rebuildable if needed

### 2. Capability gating
Before enabling execution, ORBIT should verify:

- Postgres connection available
- `vector` extension installed
- target dimension compatibility with active embedding model
- index creation status (if approximate search is introduced)

### 3. Backend enablement
When ready, `PostgresMemoryRetrievalBackend` should move from:
- explainable stub

to:
- capability-gated execution backend

A safe progression would be:
1. exact similarity SQL without ANN index
2. explain/inspection validation
3. optional index-backed optimization

### 4. Inspector validation loop
The current compare mode should be kept during migration so ORBIT can compare:

- application-side ranking
- postgres-side ranking
- top result ids
- score differences / ranking divergence

This should reduce blind migration risk.

## Recommended migration sequence

1. add pgvector-native derived embedding storage
2. populate it from existing `MemoryEmbedding` rows
3. implement exact SQL similarity in `PostgresMemoryRetrievalBackend`
4. enable compare-mode validation without switching default execution
5. compare top-k agreement against application backend
6. only then consider promoting postgres retrieval beyond stub mode

## Non-goals during first pgvector activation

- changing canonical memory ownership
- removing application backend
- moving transcript search into the same system
- hiding backend differences from the inspector

## Key principle

The PostgreSQL path should become a **better execution backend**, not a reason to collapse ORBIT's current boundaries.

That means:
- transcript remains transcript
- memory remains a distinct persistence layer
- embeddings remain derivative
- retrieval remains inspectable
- compare mode remains valuable until the postgres path is trusted
