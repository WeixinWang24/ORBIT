# Knowledge Surface First Slice Draft

## Goal

Reattach the knowledge surface under `runtime_core_minimal` without recoupling it into provider projection, capability execution, or SessionManager canonical truth.

The first slice is limited to two runtime-owned boundaries:

- pre-turn auxiliary input
- post-turn observation

## Runtime Placement

Knowledge surface entry points are owned by `SessionManager`.

### Pre-turn

`SessionManager` calls the auxiliary-input boundary before backend planning.

### Post-turn

`SessionManager` calls the post-turn observer after terminal materialization or continuation settlement.

## Explicit Non-Goals

The first slice does not:

- place knowledge retrieval inside provider payload build
- place Obsidian or substrate logic inside provider projection
- alter canonical runtime outcome or continuation logic
- perform synchronous heavy note writeback
- merge execution-oriented MCP into the knowledge path

## Allowed Pre-Turn Input Content

Only the following content classes may enter prompt assembly through auxiliary fragments.

### 1. Knowledge availability and preflight

Allowed:

- availability level
- recommended mode
- vault root configured / exists / readable
- substrate readiness summary

Not allowed:

- verbose environment logs
- raw diagnostics dump
- stack traces

### 2. Vault or workspace metadata hints

Allowed:

- vault name
- path scope
- note count / directory count
- top-level structure hint
- latest modified hint

Not allowed:

- large directory trees
- full note inventories
- broad path enumerations

### 3. Retrieval summary and planning guidance

Allowed:

- short retrieval summary
- short planning guidance
- confidence hint
- retrieval mode hint

Constraints:

- must remain distilled
- must remain short
- must not become raw note-body injection

### 4. Limited anchor / decision / procedural hints

Allowed:

- one primary anchor
- a small number of decision-note hints
- a small number of procedural-note hints

Constraints:

- summary only
- quantity strictly limited
- must guide orientation rather than dump source material

### 5. Memory fragments when memory is enabled

Allowed:

- a small number of query-relevant memory fragments

Constraints:

- query scoped
- not a transcript replacement
- not broad historical replay

## Disallowed Pre-Turn Input Content

The first slice must not inject:

- large raw excerpts
- full retrieval hit lists
- full note bodies
- raw substrate objects
- debug logs
- exception traces
- unrelated recall
- broad defensive overstuffing

## Pre-Turn Contract

### Input

- `session`
- `messages`
- `runtime_profile`
- `query_text`

### Output

`AuxiliaryInputCollection`

- `fragments: list[ContextFragment]`
- `metadata: dict`
- `timings: dict[str, float]`

### Semantics

The auxiliary-input boundary:

- prepares runtime-side knowledge input only
- may write observer / operation metadata
- must allow complete no-op behavior
- must not write canonical session truth
- must not trigger capability execution or governance interpretation

## Post-Turn Observation Content

The first slice post-turn observer is observation-only.

### Allowed observation categories

- latest assistant message and message kind
- turn index and runtime profile
- aligned user ↔ assistant turn pairing when needed
- memory capture metadata when enabled
- lightweight knowledge capture candidate metadata

### Not yet allowed

- direct note mutation
- synchronous note rewrite / merge
- synchronous heavy indexing
- any post-turn action that changes canonical result handling

## Post-Turn Contract

### Input

- `session`
- `plan`
- `messages`
- `runtime_profile`

### Output

`PostTurnObservationResult`

- `metadata: dict`
- `timings: dict[str, float]`

### Semantics

The post-turn observer:

- records observation-side metadata only
- does not mutate the just-finished runtime outcome
- does not participate in continuation planning
- may later evolve toward an async sink, but first slice remains lightweight

## Knowledge Substrate Boundary

Knowledge substrate includes retrieval and storage backends such as:

- Obsidian vault access
- knowledge retrieval/index services
- vault metadata access
- future read-only knowledge MCP access
- memory retrieval services

### Boundary rules

- substrate is consumed by knowledge-surface boundaries, not by provider projection
- substrate is not canonical truth
- substrate is not part of runtime outcome or continuation interpretation
- execution-oriented MCP remains outside the knowledge surface

## Current Code Mapping

### Pre-turn

- `SessionManager._collect_auxiliary_input(...)`
- `DetachedKnowledgeMemoryCollector`
- `AuxiliaryInputCollection`

### Post-turn

- `SessionManager._run_post_turn_observer(...)`
- `CompositePostTurnObserver`
- `DetachedKnowledgePostTurnObserver`
- `DetachedMemoryCaptureObserver`

### Provider constraint

Provider consumes prepared `auxiliary_fragments` only.

## Status Against Current Code

### Already achieved

- `SessionManager` owns the auxiliary-input collector
- backend planning now receives prepared `auxiliary_fragments`
- provider no longer owns the knowledge collector entry point
- post-turn observer is SessionManager-owned
- post-turn observer can combine knowledge observation and memory capture

### Still pending

- further distill allowed pre-turn content so retrieval payloads stay narrow in practice
- decide whether `DetachedKnowledgeMemoryCollector` should keep direct substrate calls or move behind a dedicated knowledge service boundary
- evolve post-turn knowledge observation from metadata-only to lightweight capture-candidate generation
- continue removing unrelated lower-level access points so knowledge substrate access stays concentrated in knowledge-surface boundaries

## First-Slice Rule Summary

Knowledge surface first slice is SessionManager-owned pre-turn auxiliary input plus SessionManager-owned post-turn observation, with strictly limited prompt input content and no provider-level or canonical-core coupling.
