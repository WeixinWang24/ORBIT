# Runtime Core Minimal — Phase Summary (2026-04-09)

Date: 2026-04-09
Status: Phase summary
Primary profile: `runtime_core_minimal`

## Purpose

Summarize the structural work completed in the current `runtime_core_minimal` cleanup phase, the remaining compatibility debt that is intentionally still in place, and the recommended transition point for the next phase of work.

---

## 1. What was achieved in this phase

### 1.1 The default runtime core was explicitly minimized
The canonical SessionManager path was reduced toward a true runtime-core baseline:

- transcript/session truth
- canonical turn execution
- provider request/stream/normalize
- assistant/user persistence

At the latest text-only hard-cut stage of this phase, provider-observed usage persistence was also detached from the canonical loop so the default path could be validated as a pure text-only runtime nucleus.

Knowledge, memory, capability, and audit concerns were detached from the default synchronous path.

### 1.2 Local runtime-path blocking was removed from the default chat path
The largest local latency source was traced to synchronous knowledge retrieval embedded in provider payload build.
That path was detached from the default runtime profile, bringing runtime behavior back toward provider-dominated latency rather than local augmentation latency.

### 1.3 Explicit extension boundaries were introduced and made real in code
The following extension boundaries now exist as real code shells:

- pre-plan auxiliary input collector
- post-turn observer
- capability attach boundary
- capability surface

At the current end-state of this phase, only the post-turn observer bridge remains directly represented inside `session_manager.py`; the capability-related boundaries remain real in the codebase but are no longer carried as manager-owned slots on the active text-only core object.

### 1.4 Existing detached logic was migrated behind those boundaries
- knowledge retrieval moved behind auxiliary collector
- pre-plan memory retrieval moved behind auxiliary collector
- post-turn memory capture moved behind post-turn observer
- default capability-detach decision moved behind capability attach policy

### 1.5 Metadata layering began as a real migration, not just a concept
Metadata channels were introduced and key first-pass writers/readers were migrated:

- `core_runtime_metadata`
- `surface_projection_metadata`
- `observer_metadata`
- `capability_metadata`
- `operation_metadata`

First-pass migrations included:
- termination state → core runtime metadata
- approval state → capability metadata
- timing/payload projections → surface projection metadata
- observer outputs / detached knowledge outputs → observer metadata

### 1.6 Canonical architecture knowledge was synchronized
This phase was reflected in:

- ADR-0015 (expanded with extension-boundary refinement)
- ADR-0016 (merged-note record)
- runtime/core wiring inventory
- extension interface draft
- metadata layering draft
- runtime-core cleanup checklist

---

## 2. What remains intentionally transitional

The following are known compatibility/debt items that remain by design for now.

### 2.1 Remaining compatibility/debt note
The earlier compatibility fallbacks for:

- `active_run_descriptor`
- `_pending_context_assembly`
- `_pending_provider_payload`
- selected projection / termination readers

have now been hard-cut from the main path.

The primary remaining metadata compatibility holdout is:

- `context_usage`

### 2.2 Usage metadata compatibility
Provider-observed token usage is now projected through `operation_metadata["usage_projection"]` for runtime-surface consumers.
The older `context_usage` session-root block remains as compatibility/accounting storage behind `ContextAccountingService`, but runtime-facing reads should prefer the operation channel projection rather than treating root metadata as the primary surface contract.

### 2.3 Detached boundaries are real, but still mostly unbound on the default profile
The extension boundaries now exist structurally, but the default `runtime_core_minimal` path keeps them detached/no-op by default.
This is intentional.

---

## 3. Architectural state at the end of this phase

At the end of this phase, ORBIT can be described as:

### Runtime Core
- small, explicit, truth-bearing default path

### Runtime Surface
- provider-facing request/stream lifecycle
- operator/CLI-facing projection and status surfaces

### Detached Extension Boundaries
- auxiliary input collector
- post-turn observer
- capability attach boundary
- capability surface

### Bypassed legacy prototype block
The old tool/governance/approval/usage prototype block is no longer part of the active `session_manager.py` file. It has been removed from the Python runtime fact surface and preserved instead in `src/orbit/runtime/core/session_manager.md` as a legacy code dump for potential future recycling.

### Metadata discipline
- channel-first structure has started
- root-level metadata is no longer assumed to be the only or preferred integration path

---

## 4. Recommended handoff to the next phase

The next phase should not continue expanding runtime-core structure work by default.
Instead, it should primarily move to:

### provider-facing runtime optimization
- request/stream behavior
- latency shaping
- runtime-facing payload policy

### selective reattachment work
- reattach one detached concern at a time through the explicit boundaries
- avoid reintroducing direct coupling into SessionManager/provider core paths

### compatibility debt cleanup when needed
- remove metadata fallback writes/readers only after all significant readers have migrated

---

## 5. Practical conclusion

This phase successfully changed the runtime from:

- a mixed core-plus-augmentation path with hidden synchronous coupling

into:

- a clearer `runtime_core_minimal` nucleus surrounded by explicit extension boundaries and early metadata discipline.

That is the main achievement to preserve going forward.
