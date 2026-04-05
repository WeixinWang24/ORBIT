# ORBIT Memory + RAG First Slice Design

## Status
Draft for active implementation phase.

## Why this exists

ORBIT is now entering transcript and memory persistence work.
This phase adds a new constraint:
- durable memory should be retrievable through a local embedding-based RAG path
- the initial retrieval path should be able to run on the local machine with a small embedding model
- PostgreSQL is the primary persistence direction; SQLite remains fallback only

This note defines the first bounded shape for that work.

## Architectural alignment

This design must preserve existing ORBIT boundaries:

- `ADR-0003` — runtime events are not the same as UI/session messages
- `ADR-0004` — transcript/history persistence is distinct from store/control persistence
- `ADR-0010` — session-visible transcript, session-readable runtime metadata, and runtime/operator scope remain separated

Therefore memory is **not** treated as:
- raw transcript duplication
- a catch-all event log
- a generic context blob mixed directly into session transcript truth

## First-slice memory layers

### 1. Transcript layer
Canonical session-visible conversational history.

Examples:
- user messages
- assistant replies
- transcript-visible tool results
- approval artifacts that belong in visible conversational scope

Primary purpose:
- visible history
- session replay
- user-facing continuity

### 2. Runtime metadata / memory-candidate layer
Session-associated but not automatically transcript-visible.

Examples:
- turn summaries
- extracted facts/preferences/decisions
- retrieval snapshots
- memory extraction diagnostics
- compression/summarization artifacts

Primary purpose:
- bridge between raw transcript and durable memory
- preserve inspectability without polluting the visible transcript

### 3. Durable memory layer
Cross-session memory records with explicit semantic typing.

Examples:
- stable user preference
- architecture decision memory
- project status memory
- unresolved commitment / TODO memory
- durable lesson / operating rule

Primary purpose:
- retrieval-oriented continuity
- future context assembly input
- cross-session recall

### 4. Embedding index layer
Vectorized retrieval substrate for memory records.

Primary purpose:
- semantic retrieval over durable memory
- later support retrieval over transcript summaries when appropriate

This layer is derivative, not canonical truth.
The canonical truth remains the memory record plus transcript/history/store layers.

## First-slice persistence posture

### Canonical persistence
PostgreSQL-first.

Expected first-slice tables/families:
- `sessions`
- `session_messages`
- `context_artifacts`
- `memory_records`
- `memory_embeddings`
- optionally later: `memory_links`, `memory_extractions`

### Fallback persistence
SQLite remains available as fallback only.

Fallback rule:
- schema shape should stay migration-friendly
- do not introduce SQLite-only assumptions
- vector retrieval fallback may begin as application-side brute-force similarity over stored vectors if needed

## Proposed first-slice memory record model

A durable memory record should carry at least:

- `memory_id`
- `scope` (`session`, `durable`)
- `memory_type`
  - `user_preference`
  - `project_fact`
  - `decision`
  - `todo`
  - `lesson`
  - `summary`
- `source_kind`
  - `transcript_message`
  - `context_artifact`
  - `manual`
  - `derived_summary`
- `session_id` nullable
- `run_id` nullable
- `source_message_id` nullable
- `summary_text`
- `detail_text`
- `tags`
- `salience`
- `confidence`
- `created_at`
- `updated_at`
- `archived_at` nullable
- `metadata` JSON

## Proposed first-slice embedding record model

A memory embedding record should carry at least:

- `embedding_id`
- `memory_id`
- `model_name`
- `embedding_dim`
- `content_sha1`
- `vector`
- `created_at`
- `metadata` JSON

Important rule:
- embeddings are disposable derivatives
- if embedding model/version changes, embeddings can be rebuilt
- memory records remain canonical

## Retrieval posture

### Query flow
1. user turn arrives
2. ORBIT determines whether memory retrieval is needed
3. query text is embedded locally
4. retrieve top-k memory candidates from stored memory embeddings
5. optional symbolic/rule filtering by tags, scope, recency, confidence
6. retrieved memory results are inserted into context assembly as auxiliary context fragments
7. transcript remains canonical; retrieval results are contextual aids, not rewritten history

### Current implementation checkpoint
The active implementation has now moved beyond placeholder recent-memory selection.
Current retrieval mode is:
- local embedding generation via sentence-transformers
- embedding persistence per `MemoryRecord`
- application-side cosine similarity over stored vectors
- retrieval projection into `auxiliary_context_fragments`

This is intentionally a first real semantic retrieval step, not yet the final retrieval architecture.
It keeps Postgres/SQLite schema stable while deferring vector-extension decisions.

### First retrieval target
Only durable memory records.

Why:
- simplest clean boundary
- avoids transcript + memory conflation
- transcript history already has its own continuity path

### Later retrieval targets
Possible later additions:
- session summaries
- compressed historical transcript segments
- project notes/workspace facts

## Local model posture

The local machine can support a small embedding model.
The first implementation should prefer a compact Hugging Face sentence embedding model suitable for Apple Silicon local execution.

Initial recommended family:
- `sentence-transformers/all-MiniLM-L6-v2` as a practical bootstrap default

Notes:
- this is not necessarily the final model
- model choice should remain configurable
- implementation should avoid binding memory architecture to one vendor/model family

## Python dependency posture

The Orbit Conda environment should include packages needed for local embedding inference:

- `torch`
- `transformers`
- `sentence-transformers`
- `huggingface_hub`

Optional later additions:
- `pgvector` integration path or SQLAlchemy-level vector support
- ONNX / Metal-specific acceleration path
- reranker support

## Retrieval and context-assembly boundary

Retrieved memory must enter ORBIT through the provider-agnostic context assembly layer.
It should become auxiliary context fragments rather than transcript-visible messages.

That means:
- retrieval results should be inspectable
- retrieval results should be attributed to source memory ids
- retrieval results should not masquerade as user or assistant transcript entries

## First implementation sequence

1. define memory domain models
2. extend store boundary for memory record persistence
3. add PostgreSQL-first tables for memory records and embeddings
4. add fallback SQLite implementations
5. add local embedding service abstraction
6. add memory extraction hook after session turn finalization
7. add retrieval hook during context assembly
8. expose retrieval/debug inspection in notebook and inspector surfaces

## Non-goals for first slice

- full autonomous memory writing policy
- heavy knowledge graph modeling
- multi-stage reranking pipeline
- large-scale transcript chunk vectorization
- final retention/compaction policy
- final Postgres vector extension decision

## Key rule

Memory retrieval should improve continuity without becoming a hidden second transcript.
Canonical truth stays separated:
- transcript for visible conversation history
- runtime metadata for inspectable non-visible session facts
- durable memory for cross-session recall
- embeddings for retrieval only
