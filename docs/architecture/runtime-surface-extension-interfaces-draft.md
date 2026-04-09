# Runtime Surface Extension Interfaces (Draft)

Date: 2026-04-09
Status: Draft (auxiliary collector + post-turn observer now have real interface shells)
Default runtime profile: `runtime_core_minimal`

## Purpose

This document sketches the first extension interfaces that should sit *around* the `runtime_core_minimal` SessionManager path rather than *inside* it.

It is a follow-up to:

- `docs/architecture/runtime-surface-core-wiring-inventory.md`
- ADR-0006 (`runtime_core_minimal` as the default SessionManager path)

Goal:

- allow future information/capability reattachment
- preserve the latency and boundary guarantees of the default runtime core
- avoid recoupling knowledge, memory, tools, and audit back into the canonical synchronous turn path

---

## 1. Design rule

The default runtime path remains:

1. transcript/session truth
2. provider request/stream/normalize
3. assistant/user persistence
4. usage persistence
5. bounded return to the runtime surface

Everything else should attach through explicit interfaces.

---

## 2. Interface A — Pre-plan auxiliary input collector

### Role

Collect optional auxiliary information *before* provider payload assembly.

### Why it exists

Knowledge and memory retrieval were previously embedded directly in provider payload build. That made the default path slow and hard to reason about.

This interface isolates those concerns so the provider path can receive already-collected auxiliary inputs rather than performing hidden retrieval itself.

### Suggested contract

```python
class AuxiliaryInputCollector(Protocol):
    def collect(
        self,
        *,
        session: ConversationSession | None,
        messages: list[ConversationMessage],
        runtime_profile: str,
        query_text: str,
    ) -> AuxiliaryInputCollection:
        ...
```

### Current implementation status

A real interface shell now exists in:

- `src/orbit/runtime/extensions/auxiliary_input.py`

Current concrete implementations:

- `NoOpAuxiliaryInputCollector`
- `DetachedKnowledgeMemoryCollector`

The detached collector already contains migrated knowledge/memory collection logic, but the default `runtime_core_minimal` path keeps it disabled.

### Allowed use cases

- knowledge fragments
- memory fragments
- future retrieval outputs
- external context packs
- provenance-tagged attachments

### Constraints

- default `runtime_core_minimal` path should use a no-op collector
- collector execution must be explicitly attached by profile/policy
- provider backend should consume auxiliary fragments, not perform direct retrieval itself

---

## 3. Interface B — Post-turn observer

### Role

Observe turn completion and run non-core side effects *after* the canonical turn finishes.

### Why it exists

Post-turn memory capture, audit logging, and artifact emission should not block the minimal core path by default.

### Suggested contract

```python
class PostTurnObserver(Protocol):
    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        ...
```

### Current implementation status

A real interface shell now exists in:

- `src/orbit/runtime/extensions/post_turn_observer.py`

Current concrete implementations:

- `NoOpPostTurnObserver`
- `DetachedMemoryCaptureObserver`

The detached observer already contains migrated memory-capture logic, but the default `runtime_core_minimal` path keeps it disabled/unbound.

### Allowed use cases

- memory capture
- artifact persistence
- event sinks
- analytics / diagnostics
- external projections

### Constraints

- default `runtime_core_minimal` path should attach no-op observers
- heavy observers should be async/off-path when possible
- observers must not be required for transcript correctness

---

## 4. Interface C — Capability attach boundary

### Role

Attach tools/MCP/capability execution through an explicit runtime profile rather than default core routing.

### Why it exists

Tool request closure, approval handling, and governance logic are valid capabilities, but they should not be hidden inside the default runtime-core path.

### Suggested contract

```python
class CapabilityAttachPolicy(Protocol):
    def decide(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityAttachDecision:
        ...
```

### Current implementation status

A real attach-policy interface shell now exists in:

- `src/orbit/runtime/extensions/capability_attach.py`

Current concrete implementations:

- `RuntimeCoreMinimalCapabilityPolicy`
- `PermissiveCapabilityAttachPolicy`

The default runtime-core-minimal path now routes tool/capability attach decisions through this boundary instead of hard-coding the detach branch directly inside `_finalize_session_plan(...)`.

A real capability-surface interface shell also now exists in:

- `src/orbit/runtime/extensions/capability_surface.py`

Current concrete implementations:

- `NoOpCapabilitySurface`
- `RegistryBackedCapabilitySurface`

The default runtime-core-minimal path keeps capability exposure detached/no-op, but there is now an explicit surface layer available behind the attach boundary.

A first `RuntimeOutcomeDispatcher` shell now also exists in:

- `src/orbit/runtime/core/outcome_dispatcher.py`
- `src/orbit/runtime/core/outcomes.py`

Current role:
- resolve raw surface outcomes into a `ResolvedRuntimeOutcome`
- resolve runtime patch targets before SessionManager applies canonical mutation
- classify continuation directives (`continue`, `waiting_for_approval`, `governance_blocked`, `substrate_blocked`, `detached`, fallback `paused`) outside the SessionManager core shell

### Allowed use cases

- capability-enabled profiles
- explicit MCP-enabled runtime modes
- future tool/governance reattachment

### Constraints

- default `runtime_core_minimal` path returns false
- tool execution should be reintroduced through capability profiles, not accidental default branching
- approval/governance should remain a separate surface from minimal runtime chat

---

## 5. Usage note — token usage should project through the operation channel

Provider-observed token usage should be surfaced to runtime/CLI/workbench consumers through the Operation Surface rather than being reintroduced as SessionManager-owned canonical turn truth.

Why:

- usage is runtime observability and operator-facing accounting
- it should remain queryable without polluting the host runtime nucleus
- SessionManager correctness should not depend on usage projection wiring

Recommended split:

- **provider/accounting layer** records observed usage through `ContextAccountingService`
- **operation channel** exposes `usage_projection` for runtime-surface consumers
- **compatibility storage** may continue to mirror usage in session metadata while migration is in progress

## 6. Interface D — Runtime metadata channel (structured)

### Role

Provide a disciplined place for cross-layer metadata instead of using session metadata as an unbounded catch-all.

### Why it exists

Session metadata is convenient, but without structure it becomes a hidden transport between core and detached surfaces.

### Suggested partition

- `core_runtime_metadata`
- `surface_projection_metadata`
- `observer_metadata`
- `capability_metadata`

### Constraints

- core metadata should remain small and truth-bearing
- observer/surface metadata should not silently affect canonical turn correctness
- detached surfaces should not depend on undocumented metadata keys

---

## 7. Interface E — Runtime surface status projection boundary

### Role

Expose runtime-facing projections to UI surfaces without pushing UI concerns down into core.

### Why it exists

Status, usage display, and workbench projections are useful, but should remain a surface concern rather than becoming part of SessionManager execution logic.

### Suggested contract

```python
class RuntimeStatusProjector(Protocol):
    def project(self, *, session_manager: SessionManager) -> dict[str, Any]:
        ...
```

### Allowed use cases

- usage projections
- status summaries
- build pointer summaries
- runtime mode/profile display

### Constraints

- should read from core truth, not define it
- should not introduce synchronous turn-time work

---

## 8. Recommended first implementation sequence

### Phase 1

- keep `runtime_core_minimal` as default
- provider payload build consumes only explicit auxiliary fragments
- no-op/default implementations for all extension interfaces

### Phase 2

- reintroduce one detached surface at a time through explicit profile attachment
- start with a single low-risk observer or auxiliary collector
- measure added latency and coupling before expanding

### Phase 3

- define capability-enabled profiles separately from minimal runtime chat
- keep tool/governance flows out of the default profile

---

## 9. Immediate engineering guidance

When adding new runtime-facing information in the near future, ask:

1. Is this required for transcript/provider truth?
   - If yes, it may belong in core.
2. Is this optional context before planning?
   - Use auxiliary input collector.
3. Is this a side effect after turn completion?
   - Use post-turn observer.
4. Is this tool/capability behavior?
   - Use capability attach boundary.
5. Is this just status/UI projection?
   - Use runtime surface projection.

If the answer is unclear, do not attach it directly to `run_session_turn(...)` by default.
