# Runtime Metadata Layering (Draft)

Date: 2026-04-09
Status: Draft
Default runtime profile: `runtime_core_minimal`

## Purpose

Prevent `session.metadata` from becoming a hidden cross-layer transport bus after the runtime core and extension boundaries have been clarified.

## Metadata channels

### 1. `core_runtime_metadata`
For truth-bearing runtime state.

Current examples:
- `terminated`
- `termination_reason`
- provider-observed usage ownership remains core-level truth (`context_usage` currently still stored at session root for compatibility; future migration may move it under this channel)

### 2. `surface_projection_metadata`
For UI/runtime-surface projections and diagnostics.

Current examples:
- `last_submit_timing_probe`
- `last_provider_payload`

### 3. `observer_metadata`
For post-turn observers and detached auxiliary/analytic outputs.

Current examples:
- `last_memory_capture`
- `last_knowledge_availability`
- `last_knowledge_vault_metadata`
- `last_knowledge_bundle`
- `last_knowledge_error`

### 4. `capability_metadata`
For tool/capability/governance-attach related state.

Current examples:
- `pending_approval`

## Current implementation helpers

Implemented in:
- `src/orbit/runtime/extensions/metadata_channels.py`

Helpers:
- `core_runtime_metadata(...)`
- `surface_projection_metadata(...)`
- `observer_metadata(...)`
- `capability_metadata(...)`
- `set_core_runtime_metadata(...)`
- `set_surface_projection_metadata(...)`
- `set_observer_metadata(...)`
- `set_capability_metadata(...)`

## First migration status

### Migrated in first pass
- `terminated` / `termination_reason` → `core_runtime_metadata`
- `pending_approval` → `capability_metadata`
- `last_submit_timing_probe` → `surface_projection_metadata`
- `last_provider_payload` → `surface_projection_metadata`
- memory capture summary → `observer_metadata`
- detached knowledge collector outputs → `observer_metadata`
- `active_run_descriptor` → `core_runtime_metadata`
- `_pending_context_assembly` → `surface_projection_metadata`
- `_pending_provider_payload` → `surface_projection_metadata`

### Intentionally not fully migrated yet
- `context_usage`

Current note:
- the items above were subsequently hard-cut to channel-only on the main path during the same 2026-04-09 cleanup sequence
- `context_usage` remains the main compatibility holdout because it is already part of runtime truth and compaction groundwork

## Rule of thumb

If new metadata is being added, ask:

1. Does runtime correctness depend on it?
   - use `core_runtime_metadata`
2. Is it primarily for CLI/status/runtime projection?
   - use `surface_projection_metadata`
3. Is it emitted by observer/auxiliary/off-path logic?
   - use `observer_metadata`
4. Is it tool/capability/governance attach state?
   - use `capability_metadata`

If none fit cleanly, do not write directly to the session root by default.
