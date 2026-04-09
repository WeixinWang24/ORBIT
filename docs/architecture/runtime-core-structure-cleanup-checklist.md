# Runtime Core Structure Cleanup Checklist

Date: 2026-04-09
Status: Working checklist
Default runtime profile: `runtime_core_minimal`

## Purpose

Capture what has already been structurally cleaned up around `runtime_core_minimal`, what remains transitional, and what should be migrated next to avoid future recoupling.

---

## 1. Completed structural work

### 1.1 Runtime core baseline
- `runtime_core_minimal` established as the default runtime profile
- SessionManager default path reduced to runtime-core essentials
- knowledge / memory / capability / audit concerns detached from the default synchronous core path

### 1.2 Runtime extension boundaries now real in code
- pre-plan auxiliary input collector
- post-turn observer
- capability attach boundary
- capability surface

### 1.3 Current migrated detached logic
- knowledge retrieval moved behind auxiliary input collector
- pre-plan memory retrieval moved behind auxiliary input collector
- post-turn memory capture moved behind post-turn observer
- default capability-detach decision moved behind capability attach boundary

### 1.4 Metadata layering started
- helper module added: `src/orbit/runtime/extensions/metadata_channels.py`
- first-pass metadata channels introduced:
  - `core_runtime_metadata`
  - `surface_projection_metadata`
  - `observer_metadata`
  - `capability_metadata`

---

## 2. Transitional items not fully migrated yet

These are known partial states and should not be forgotten.

### 2.1 Remaining compatibility holdout
- compatibility storage under `context_usage`

Current state note:
- the earlier compatibility fallbacks for `active_run_descriptor`, `_pending_context_assembly`, and `_pending_provider_payload` have now been hard-cut from the main path
- runtime-facing usage reads now prefer `operation_metadata["usage_projection"]`
- `context_usage` remains as compatibility/accounting storage behind `ContextAccountingService`, not as the primary runtime-surface contract

### 2.2 Direct root-level metadata readers still likely exist
Potential areas:
- web inspector
- status/projection helpers
- testing utilities
- older governance/service helpers

### 2.3 Capability residue still exists outside the active manager core
Even though `tool_registry` is no longer manager-owned state on the active `SessionManager` object, capability/tool residue still exists in surrounding runtime modules and should be treated as a controlled reattachment risk.

---

## 3. High-risk old wiring still worth watching

### 3.1 Provider payload path
Risk:
- future contributors may reinsert retrieval directly into provider payload build instead of using the auxiliary collector

### 3.2 SessionManager finalize path
Risk:
- future post-turn side effects may be added directly to `_finalize_session_plan(...)` instead of the observer boundary

### 3.3 Metadata root as an escape hatch
Risk:
- future work may bypass metadata channels and write straight to `session.metadata[...]`

### 3.4 Tool/governance fallback logic
Risk:
- future capability work may bypass capability attach boundary and route directly into tool closure/policy logic

---

## 4. Documentation synchronization still recommended

These files should be checked and updated as needed so the knowledge base matches the code reality:

- `50_ADRs/ADR-INDEX.md`
- `50_ADRs/INDEX.md`
- `20_Architecture/12_ORBIT_Site_Map.md`
- `20_Architecture/10_Runtime_Loop_Sketch.md`
- any architecture summaries that still describe old direct coupling patterns

---

## 5. Recommended next migration order

### Priority 1 — operation-channel usage cleanup
1. finish migrating runtime-facing usage readers to `operation_metadata["usage_projection"]` and reduce direct dependence on compatibility storage under `context_usage`

### Priority 2 — bypassed legacy residue handling
2. keep the following prototype/tool/governance/usage functions out of the canonical path unless and until they are reattached through the new boundaries (they are no longer part of the active `session_manager.py` fact surface and are preserved as legacy dump/reference material):
   - `execute_tool_request(...)`
   - `append_tool_result_message(...)`
   - `list_open_session_approvals(...)`
   - `resolve_session_approval(...)`
   - `_execute_non_approval_tool_closure(...)`
   - `_maybe_materialize_rejected_tool_reissue_guard(...)`
   - `_apply_capability_attach_boundary(...)`
   - `_route_tool_request_through_policy(...)`
   - `_evaluate_policy_for_plan(...)`
   - `_apply_policy_decision(...)`
   - `_apply_policy_execution_boundary(...)`
   - `_materialize_policy_outcome_from_spec(...)`
   - `_materialize_policy_message_outcome(...)`
   - `_materialize_governed_tool_failure_outcome(...)`
   - `_get_tool_governance_metadata(...)`
   - `_mark_permission_authority_rejection(...)`
   - `_get_pending_approval(...)`
   - legacy loop-local usage persistence hooks (replaced by provider/accounting -> operation-channel usage projection)

### Priority 3 — reattachment discipline
3. ensure future capability/governance work binds through capability attach boundary + capability surface instead of direct SessionManager fallback paths
4. ensure future usage reattachment binds through explicit side-effect/channel wiring rather than direct restoration of old loop-local hooks

---

## 6. Rule for future changes

Before adding new runtime-adjacent logic, ask:

1. Does this belong to core runtime truth?
2. Is it pre-plan auxiliary input?
3. Is it post-turn observer work?
4. Is it capability/governance attachment?
5. Is it only projection/status metadata?

If the answer is unclear, do not attach it directly to the default synchronous `runtime_core_minimal` path.
