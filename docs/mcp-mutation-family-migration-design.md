# MCP Mutation Family Migration Design

## Purpose
This note defines how ORBIT should migrate its current built-in grounded filesystem mutation family toward an MCP-hosted shared capability family without collapsing runtime-local grounding and governance semantics.

The problem is not that the current built-in mutation tools are wrong.
The problem is that ORBIT is expected to support more than one agent loop runtime over time, including multi-agent and architecture-diverse runtimes.
A runtime-private mutation family does not scale as well as a shared capability family.

The design goal is therefore:

> Move reusable filesystem mutation capability semantics into MCP-hosted capability surfaces,
> while preserving runtime-local grounding, approval, transcript, and inspection behavior.

---

## Current state

ORBIT currently has a grounded built-in mutation family implemented as native tools:
- `native__write_file`
- `native__replace_in_file`
- `native__replace_all_in_file`
- `native__replace_block_in_file`
- `native__apply_exact_hunk`

These tools already share important runtime behavior:
- approval required
- grounding-aware mutation gate
- fresh full-read grounding required
- layered failure semantics
- shared result-shaping fields such as `mutation_kind`, `path`, `replacement_count`, `match_count`, `change_summary`, `before_excerpt`, `after_excerpt`, `failure_layer`, and `write_readiness`

This family is already architecturally coherent.
The migration question is not whether the family should exist.
The migration question is where the reusable parts of that family should live.

---

## Architecture decision direction

The correct long-term direction is:
- reusable mutation capability semantics should move toward MCP-hosted shared capability surfaces
- runtime-local grounding/governance semantics should remain in ORBIT runtime adapter/orchestration layers

This means ORBIT should not treat MCP as "just another transport" for tools.
Instead, MCP should become the cross-runtime capability substrate for reusable filesystem mutation families.

---

## Layer split

### 1. MCP capability layer
This layer should own reusable mutation capability semantics.
Examples:
- `write_file`
- `replace_in_file`
- `replace_all_in_file`
- `replace_block_in_file`
- `apply_exact_hunk`
- future `apply_exact_multi_hunk`

Responsibilities of this layer:
- path-safe filesystem mutation within the declared workspace root
- exact matching and replacement semantics
- capability-local semantic failure reporting
- structured mutation result payloads

Non-responsibilities of this layer:
- session grounding truth
- fresh/stale read-readiness policy
- approval policy
- transcript truth rules
- runtime event persistence
- runtime inspection policy

### 2. MCP adapter layer inside ORBIT
This layer should adapt MCP capability surfaces into ORBIT tool runtime objects.

Responsibilities of this layer:
- MCP tool discovery and wrapping
- naming normalization consistent with ORBIT naming policy
- mapping MCP result payloads into ORBIT tool-result handling
- preserving tool metadata required for governance and inspection

This layer should not become the place where mutation semantics are reinvented.
It should adapt, not duplicate.

### 3. Runtime-local policy/orchestration layer
This layer should remain inside ORBIT runtime.

Responsibilities of this layer:
- grounding-readiness computation
- approval and policy insertion
- transcript-visible result shaping rules
- runtime event and tool invocation persistence
- inspection/workbench projections

This is where ORBIT enforces:
- permission allow is necessary but not sufficient for mutation
- fresh full-read grounding is required for grounded mutation

---

## Migration invariants

The following invariants must survive migration from built-in to MCP-hosted mutation tools.

### 1. Naming invariant
- built-in/native tools keep explicit `native__` names
- MCP mutation tools expose canonical names where possible

Examples:
- native: `native__replace_in_file`
- MCP: `replace_in_file`

### 2. Result contract invariant
The structured mutation result contract must remain stable across built-in and MCP-hosted implementations.

Current stable fields include:
- `mutation_kind`
- `path`
- `replacement_count`
- `match_count`
- `change_summary`
- `before_excerpt`
- `after_excerpt`
- `failure_layer`
- `write_readiness` where gate failures are surfaced at runtime layer

Important distinction:
- capability-local semantic result fields should originate from the capability implementation
- runtime-local gate fields such as `write_readiness` should still be injected by runtime policy/orchestration

### 3. Failure taxonomy invariant
Migration must preserve ORBIT's layered mutation failure model:
- `governance`
- `grounding_readiness`
- `tool_semantic`
- `runtime_execution`

MCP hosting must not collapse these into a single opaque tool failure.

### 4. Governance insertion invariant
Grounding-aware mutation gating remains runtime-local.

The MCP capability layer may say:
- this mutation semantically matches
- this mutation semantically fails

Only the runtime may say:
- this mutation is not allowed now because grounding is insufficient or stale

### 5. Transcript/runtime separation invariant
Migration must not collapse runtime-local grounding truth into transcript truth.
This preserves the earlier ORBIT decision that transcript is canonical visible conversation truth while grounding/session/runtime metadata remain separate runtime substrate.

---

## What should migrate first

The recommended first migrated mutation capability is:
- `replace_in_file`

### Why `replace_in_file` first
It is the best first migration target because:
- it is semantically richer than whole-file write
- it is simpler than exact hunk or multi-hunk application
- it already fits the shared mutation-family contract well
- it is a natural bridge between naive write tools and more advanced patch-style tools

This makes it an ideal first MCP-hosted mutation family member.

---

## Recommended migration phases

### Phase M1 — design only
- document the layer split
- document migration invariants
- choose the first migrated tool
- confirm naming and result-contract policy

### Phase M2 — first migrated mutation capability
- implement MCP-hosted `replace_in_file`
- preserve native `native__replace_in_file` during transition
- adapt MCP `replace_in_file` through the existing MCP adapter path
- ensure runtime-local grounding gate applies identically to native and MCP variants

Current implementation progress:
- the filesystem MCP server now exposes canonical `replace_in_file`
- ORBIT MCP governance now classifies `replace_in_file` as a permission-authority mutation tool
- runtime-local grounding gating now applies to both native `native__replace_in_file` and MCP-hosted `replace_in_file`
- MCP semantic failure is now normalized into ORBIT's layered mutation failure model instead of being treated as unconditional success

### Phase M3 — contract and behavior alignment
- verify native and MCP variants return aligned structured mutation result shapes
- align inspection projection across native and MCP variants
- ensure tests cover both variants under shared runtime policy expectations

### Phase M4 — family expansion
After the first migrated capability is stable, migrate additional family members in this likely order:
1. `replace_all_in_file`
2. `replace_block_in_file`
3. `apply_exact_hunk`
4. future `apply_exact_multi_hunk`
5. only later, richer diff/multi-hunk families if still justified

---

## Why not migrate everything immediately

Immediate full migration would create several risks:
- duplicated built-in and MCP behavior drifting out of sync
- unclear ownership of semantic vs governance failures
- result contract divergence between runtime-private and MCP-hosted variants
- accidental leakage of runtime-local grounding logic into MCP capability code

A staged migration is preferred because it keeps one boundary change legible at a time.

---

## Why not push grounding into MCP

Grounding should remain runtime-local because it depends on:
- session-scoped read-state truth
- transcript/runtime separation rules
- runtime-specific governance semantics
- future runtime diversity across ORBIT architectures

If grounding is pushed into MCP capability implementations, ORBIT would risk hard-coding one runtime's mutation-readiness model into a supposedly reusable capability layer.
That would make reuse across multiple runtimes worse, not better.

---

## Compatibility stance during migration

During migration, ORBIT should allow a transitional period where:
- built-in/native mutation tools still exist
- MCP-hosted equivalents are introduced gradually
- tests compare both paths against shared runtime invariants where appropriate

The goal is not immediate deletion of native tools.
The goal is to make reusable mutation semantics MCP-hosted without destabilizing current runtime behavior.

---

## Future consequences

If this migration succeeds, ORBIT will gain:
- a reusable filesystem mutation capability family available to multiple runtimes
- clearer separation between capability semantics and runtime governance
- easier multi-runtime experimentation without cloning tool logic
- a cleaner path toward multi-agent shared filesystem mutation capability

The cost is that ORBIT must stay disciplined about adapter boundaries and result contract consistency.

---

## Recommendation summary

ORBIT should migrate its grounded filesystem mutation family toward MCP-hosted shared capability surfaces in a staged way.

Recommended immediate next step:
- keep the current built-in family stable
- treat this document as the migration design anchor
- migrate `replace_in_file` first as the initial MCP-hosted mutation family member
- preserve runtime-local grounding-readiness, approval, transcript, and inspection policy as ORBIT-local layers
