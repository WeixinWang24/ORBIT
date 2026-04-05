# ORBIT Reference Comparison: OpenClaw Fork vs Claude Code

## Status
Working comparison for the active transcript / memory / persistence / RAG phase.

## Scope
This note compares two reference systems for ORBIT's current design work:

1. **OpenClaw fork / current Vio runtime**
   - canonical source root: `/Users/visen24/MAS/openclaw_fork`
2. **Claude Code recovered source**
   - source root: `/Volumes/2TB/MAS/openclaw-core/claude_code_src`

The goal is not to copy either system wholesale.
The goal is to extract design lessons relevant to:
- transcript truth
- session/history persistence
- memory extraction and persistence
- retrieval / RAG integration
- context assembly boundaries

## High-level conclusion

ORBIT should borrow from the two references differently:

- **From Claude Code:** adopt the boundary philosophy
  - transcript/history is not memory
  - memory is a derived continuity layer
  - memory extraction and context compaction are distinct services
  - searchable visible transcript should not silently include hidden/model-only artifacts

- **From OpenClaw fork:** adopt the retrieval engineering posture
  - embedding-provider abstraction
  - hybrid search and reranking
  - vector/index lifecycle management
  - session-file/transcript repair discipline
  - explicit memory backend and fallback strategies

Short version:

> For ORBIT's architecture, Claude Code is the better teacher.
> For ORBIT's retrieval engineering, OpenClaw fork is the stronger reference.

---

## 1. OpenClaw fork: what it teaches well

### 1.1 Session/transcript reality
Relevant paths observed:
- `src/gateway/server-methods/chat.ts`
- `src/config/sessions/transcript.ts`
- `src/agents/session-transcript-repair.ts`
- `src/config/sessions/store.ts`
- `src/config/sessions/store-migrations.ts`

What this system is good at:
- explicit session key and session file resolution
- transcript append paths with delivery-aware integration
- idempotent mirrored transcript append
- transcript update events for downstream consumers
- transcript repair when tool-call / tool-result structure becomes inconsistent

Key lesson for ORBIT:
- transcript persistence is not only "save messages"
- it also needs:
  - identity resolution
  - stable append semantics
  - event emission
  - repair / sanitization for malformed tool-call history

### 1.2 Memory retrieval engineering
Relevant paths observed:
- `src/memory/manager.ts`
- `src/memory/search-manager.ts`
- `src/memory/hybrid.ts`
- `src/memory/mmr.ts`
- `src/memory/query-expansion.ts`
- `src/memory/sqlite-vec.ts`
- `src/memory/embeddings-ollama.ts`
- `src/memory/embeddings-openai.ts`
- `src/memory/embeddings-gemini.ts`
- `src/memory/embeddings-voyage.ts`

What this system is good at:
- memory backend abstraction
- embedding provider abstraction
- hybrid lexical + vector retrieval
- fallback behavior when a preferred backend fails
- operational handling of index lifecycle, caching, and manager reuse
- explicit concern for evidence/rerank/query-expansion quality

Key lesson for ORBIT:
- once memory retrieval becomes real product infrastructure, the architecture must account for:
  - provider selection
  - embedding caching/rebuilds
  - index schema evolution
  - fallback logic
  - hybrid ranking quality
  - operational status / health visibility

### 1.3 Risk in using OpenClaw as the primary shape
OpenClaw fork is not a clean transcript-memory reference for ORBIT's core architecture.
It is a larger operational system where:
- routing
n- delivery
- session identity
- transcript persistence
- tool/runtime policy
- memory retrieval

all coexist under a heavier practical runtime.

This makes it excellent for engineering tactics, but less ideal as the primary source of ORBIT's conceptual boundaries.

### 1.4 Adopt / do not adopt for ORBIT

#### Adopt
- transcript append discipline
- transcript repair discipline
- session-store operational maturity
- embedding-provider abstraction
- hybrid retrieval ideas
- reranking / MMR ideas
- explicit fallback behavior for memory backend availability

#### Do not adopt directly
- broad runtime coupling between transcript, routing, delivery, and memory
- treating the memory subsystem as a near-peer of all runtime concerns inside one operational layer
- file-store-first operational assumptions as the long-term persistence truth for ORBIT

---

## 2. Claude Code: what it teaches well

### 2.1 Session history and memory are clearly different services
Relevant paths observed:
- `src/assistant/sessionHistory.ts`
- `src/services/SessionMemory/sessionMemory.ts`
- `src/services/SessionMemory/sessionMemoryUtils.ts`
- `src/services/extractMemories/prompts.ts`
- `src/services/compact/sessionMemoryCompact.ts`
- `src/utils/transcriptSearch.ts`

What this system is good at:
- distinguishing history/event retrieval from memory extraction
- treating memory as a maintained continuity artifact, not as transcript truth
- using explicit extraction thresholds and extraction state
- letting a background/forked agent update memory without blocking the main conversation flow
- separating session memory compaction from raw transcript retention

Key lesson for ORBIT:
- transcript/history, memory extraction, session memory, and compaction should be sibling services, not one blended store concept

### 2.2 Memory is explicitly derived, not canonical transcript truth
Observed behavior in `sessionMemory.ts` and related prompts:
- memory extraction runs conditionally after the main conversation progresses enough
- extraction writes/updates a separate session memory file
- extraction has its own prompt and save criteria
- memory updates happen after conversation flow, not as the primary conversation artifact itself

Key lesson for ORBIT:
- durable/session memory should be written from transcript-derived evidence
- transcript remains canonical visible history
- memory remains a derived continuity substrate

This aligns strongly with ORBIT's current ADR direction:
- runtime events are not transcript messages
- transcript persistence and store/control persistence are distinct
- retrieval should enter context assembly as auxiliary context, not rewritten transcript

### 2.3 Compaction is its own problem
Observed behavior in `sessionMemoryCompact.ts`:
- compaction is not "replace transcript with memory"
- instead, transcript and memory coexist while compaction manages what remains active in context budget

Key lesson for ORBIT:
- do not use durable memory as a hacky substitute for transcript history
- compaction/summarization should be its own layer above canonical transcript persistence

### 2.4 Visible transcript search is not naive serialization search
Observed behavior in `utils/transcriptSearch.ts`:
- visible-search text excludes hidden or system-only artifacts
- tool-result search tries to approximate what the UI actually renders, not just raw model-facing serialized blocks

Key lesson for ORBIT:
- searchable transcript, provider-visible transcript projection, and runtime/internal storage should be treated as different projections over related source material

This is especially important for ORBIT because:
- provider payloads
- runtime event payloads
- transcript-visible messages
- auxiliary context fragments

must not collapse into one undifferentiated searchable blob.

### 2.5 Risk in using Claude Code as the primary shape
Claude Code is a strong boundary reference, but weaker as a direct guide for ORBIT's long-term retrieval implementation because:
- the observed memory system is file/session-memory oriented
- local embedding/vector retrieval is not the dominant visible design center in the same way as OpenClaw fork's memory subsystem
- the retrieval engineering surface appears less central than the continuity/compaction surface

### 2.6 Adopt / do not adopt for ORBIT

#### Adopt
- transcript/history vs memory separation
- explicit memory extraction service
- extraction thresholds / non-blocking scheduling ideas
- compaction as a separate service
- visible transcript search discipline
- strong distinction between canonical history and derived continuity artifacts

#### Do not adopt directly
- markdown-file-first session memory as ORBIT's canonical durable-memory substrate
- background subagent extraction as the only future operating mode
- any implicit assumption that file memory is sufficient as the long-term primary storage model

---

## 3. Side-by-side comparison for ORBIT

### 3.1 Transcript truth

**OpenClaw fork**
- strong on append/update/repair operations
- strong on session file identity and transcript event emission
- transcript is operationally important and delivery-aware

**Claude Code**
- strong on conceptual boundary between visible history and derived memory
- strong on visible-search discipline
- history retrieval feels explicitly separate from memory service

**ORBIT implication**
- adopt Claude Code's boundary model
- adopt OpenClaw's append/repair operational discipline

### 3.2 Memory extraction

**OpenClaw fork**
- memory system appears oriented around indexed searchable corpus management
- stronger on retrieval infra than on clearly separated extraction-life-cycle philosophy

**Claude Code**
- memory extraction is explicit, thresholded, and derived from conversation progress
- memory service has separate lifecycle from transcript flow

**ORBIT implication**
- extraction model should look more like Claude Code
- extracted artifacts should then feed a retrieval/index layer shaped more like OpenClaw

### 3.3 Retrieval / RAG

**OpenClaw fork**
- clear winner for retrieval engineering
- embedding-provider abstraction, hybrid retrieval, reranking, fallback handling

**Claude Code**
- less obviously retrieval-centric in the observed surfaces
- stronger on continuity than on vector retrieval architecture

**ORBIT implication**
- ORBIT's RAG path should learn primarily from OpenClaw fork
- but retrieval results must still enter the runtime according to Claude Code-like boundaries

### 3.4 Persistence posture

**OpenClaw fork**
- operational session file + store reality
- practical repair/migration maintenance concerns are visible

**Claude Code**
- memory continuity seems file/service driven and operationally separate

**ORBIT implication**
- ORBIT should stay on its current path:
  - PostgreSQL-first canonical persistence
  - SQLite fallback only
  - transcript and durable memory canonical rows in store
  - embeddings as derivative rebuildable state

Neither reference should override ORBIT's current Postgres-primary persistence decision.

### 3.5 Context assembly

**OpenClaw fork**
- memory prompt sections / retrieval integration likely support direct prompt enrichment

**Claude Code**
- stronger example of not confusing memory with transcript

**ORBIT implication**
- current ORBIT decision remains correct:
  - retrieval enters `auxiliary_context_fragments`
  - transcript remains transcript
  - runtime metadata remains separate
  - compaction later becomes another derived context contributor

---

## 4. Recommended ORBIT design stance after comparison

## 4.1 Core principle

ORBIT should not become a copy of either reference.
It should instead combine:

- **Claude Code's conceptual layering**
- **OpenClaw fork's retrieval maturity**
- **ORBIT's own ADR-enforced canonical separation**

## 4.2 Recommended target layering for ORBIT

### Canonical layers
1. **Transcript store**
   - visible session history only
2. **Runtime/control store**
   - runtime events, control truth, approval state, process state
3. **Memory store**
   - session memory + durable memory records

### Derived layers
4. **Embedding store**
   - derivative vector rows for memory records
5. **Compaction/summarization artifacts**
   - derived continuity compression layers
6. **Prompt/context assembly projection**
   - history fragment
   - memory retrieval fragment
   - runtime-only fragments
   - provider payload snapshot

## 4.3 Recommended first-slice implementation direction

### Keep
- current ORBIT `PromptAssemblyPlan` shape
- retrieval injected as `auxiliary_context_fragments`
- session-turn memory capture in `SessionManager`
- Postgres-primary persistence with SQLite fallback

### Add next
1. local embedding service abstraction
2. embedding write path for `MemoryRecord`
3. app-side cosine retrieval first
4. later hybrid lexical + vector retrieval
5. later rerank / MMR if needed
6. later explicit compaction service, separate from transcript persistence

### Avoid
- storing memory only as raw markdown files as the primary ORBIT truth
- collapsing transcript + memory + runtime events into one table or one conceptual stream
- letting provider payload structure define ORBIT's internal memory/transcript taxonomy

---

## 5. Concrete adoption matrix

### Adopt from OpenClaw fork
- transcript repair mindset
- session/transcript append hygiene
- embedding-provider abstraction
- backend fallback discipline
- hybrid retrieval ideas
- reranking/MMR ideas
- vector lifecycle and health/status awareness

### Adopt from Claude Code
- transcript/history vs memory separation
- explicit memory extraction lifecycle
- thresholded/non-blocking extraction concept
- compaction as a separate continuity service
- visible transcript search discipline
- memory as derived continuity, not canonical transcript

### Do not adopt from either reference unchanged
- file-first persistence as ORBIT's long-term canonical storage model
- runtime-wide coupling that blurs transcript, memory, routing, and delivery truth
- hidden/model-only content becoming searchable/session-visible by accident

---

## 6. Final recommendation

For the active ORBIT phase, the design direction should be:

> **Architecture from Claude Code, retrieval engineering from OpenClaw fork, persistence canon from ORBIT's own Postgres-first ADR direction.**

That means:
- transcript remains canonical visible history
- memory remains a derived persistence layer
- retrieval uses embeddings/RAG but never rewrites transcript truth
- compaction comes later as a separate derived continuity layer
- embeddings remain derivative state and rebuildable

This is the cleanest path that preserves ORBIT's boundaries while still taking advantage of both reference systems' strongest ideas.
