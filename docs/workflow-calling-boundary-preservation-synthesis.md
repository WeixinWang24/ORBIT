# Workflow Calling Boundary Preservation Synthesis

This repo-local note mirrors the corresponding ORBIT knowledge-base synthesis under:
- `70_Absorbed_Reference/workflow-calling-boundary-preservation-synthesis-2026-04-04.md`

Purpose:
- keep a lightweight repo-side architectural memory of the current workflow-calling boundary direction
- preserve the most important boundary truths before implementation convenience erodes them
- point future implementation work toward the knowledge-base record for the full design rationale

## Current distilled stance

ORBIT's emerging workflow-calling direction should be treated as:
- **bounded soft process calling**
- selected by the **main model**
- bound and locked by the **host runtime**
- executed by a **scope/workflow-locked, non-sovereign orchestration runtime**
- returned as a **structured WorkflowResult**
- never treated as directly identical to main-provider-visible context

## Most important boundary truths

1. **Selection authority** stays with the main model.
2. **Binding authority** stays with the host runtime.
3. **Execution authority** in the child orchestration runtime is bounded and non-sovereign.
4. **Workflow assets in the KB are not directly executable runtime config.**
5. **WorkflowResult is host-runtime truth first.**
6. **A host-runtime projection boundary must exist between WorkflowResult and provider-visible context.**

## Minimal floor

Use the future `Workflow Calling Minimal Boundary Set (WCMBS)` as the identity floor and first-slice smoke-test boundary set.

Expected members:
- Selection Authority Preservation
- Binding-Time Workflow Lock
- Asset/Execution Separation
- Result/Projection Separation

## Why this note exists

The current risk is less “lack of capability” and more:
- prompt collapse
- delegation collapse
- note-as-config collapse
- direct result injection collapse
- convenience-driven semantic collapse in general

This note exists to preserve the boundary before detailed implementation and provider-specific projection rules are finalized.

This design line should also be understood as:
- **policy-to-code** work: the discussion produced governance-level constraints intended to shape and review future implementation
- a case of **top-down knowledge derivation**: high-level runtime pressure was used to derive authority split, lock model, object boundaries, minimal boundary floor, and future review instruments before implementation details were fixed

## Deferred on purpose

The following are intentionally not finalized yet:
- provider-facing workflow exposure mechanics
- WorkflowCall wire form
- detailed WorkflowResult projection rules
- result-kind-specific projection policies
- complete workflow registry / activation mechanics

## Next proper formalization targets

When promoted into formal architecture records, split into:
- ADR for authority split / lock model / result boundary / deferred scope
- boundary-preservation note for graphs, anti-collapse patterns, and reviewable rule blocks
