# Runtime Surface ↔ Core Wiring Inventory

Date: 2026-04-09
Status: Working inventory
Default runtime profile: `runtime_core_minimal`

## Purpose

This inventory captures the current wiring between:

- **Runtime Core** — the minimal SessionManager-centered execution truth
- **Runtime Surface** — the provider-facing and CLI-facing runtime path
- **Detached Surfaces** — capability, knowledge, memory, and audit layers that remain in-tree but are no longer part of the default synchronous core path

The goal is to:

1. identify current synchronous wiring that still defines the runtime path
2. identify detached wiring that could accidentally flow back into core later
3. define preferred future ingress points for new information/capability attachments

---

## 1. Current default core path (`runtime_core_minimal`)

### 1.1 Entry: PTY runtime CLI submit

Primary path:

- `src/orbit/interfaces/pty_runtime_cli.py`
  - `_start_background_submit(...)`
  - submit thread / busy lifecycle
  - inflight assistant partial text
  - stream-completed notification

This is a **runtime surface** entrypoint, not the core itself.

### 1.2 Runtime surface adapter bridge

- `src/orbit/interfaces/runtime_adapter.py`
  - `SessionManagerRuntimeAdapter.send_user_message(...)`
  - `SessionManagerRuntimeAdapter.get_workbench_status(...)`
  - context usage projection mapping
  - session/message mapping for UI surfaces

This adapter is the primary **surface-to-core bridge**.

### 1.3 Core turn execution

- `src/orbit/runtime/core/session_manager.py`
  - `run_session_turn(...)`
  - `_plan_from_messages_and_record_usage(...)`
  - `_finalize_session_plan(...)`

In the current default profile, this is the **canonical runtime core**.

### 1.4 Provider-facing runtime path

- `src/orbit/runtime/providers/openai_codex.py`
  - `plan_from_messages(...)`
  - `build_request_payload_from_messages(...)`
  - `normalize_events(...)`

This is the primary **runtime surface provider bridge**.

---

## 2. Core-synchronous wiring that remains active by default

These wires are still part of the default runtime path and therefore define latency/behavior of the minimal runtime core.

### 2.1 Transcript truth wiring

- `SessionManager.append_message(...)`
- `SessionManager.list_messages(...)`
- assistant/user message persistence through the store

Why active:
- required for session truth and transcript continuity

### 2.2 Provider payload assembly wiring

- `OpenAICodexExecutionBackend.build_request_payload_from_messages(...)`
- `build_text_only_prompt_assembly_plan(...)`
- `messages_to_codex_input(...)`

Why active:
- required to shape the provider request for the current turn

### 2.3 Provider stream + normalization wiring

- `stream_sse_events(...)`
- `normalize_events(...)`
- `messages_to_codex_input(...)`
- provider-native `function_call_output` reinjection for tool results when `provider_call_id` is present
- `on_partial_text`
- `on_stream_completed`

Why active:
- required for runtime response delivery
- required for correct continuation closure after provider-issued tool calls

### 2.4 Usage/accounting wiring

- `ContextAccountingService.normalize_provider_usage(...)`
- `ContextAccountingService.record_observed_usage(...)`
- `operation_metadata["usage_projection"]`
- compatibility storage under session metadata `context_usage`

Why active:
- required for runtime observability and future compaction pressure tracking
- projected usage now belongs to the operation channel rather than the SessionManager core path

### 2.5 Surface status projection wiring

- `SessionManagerRuntimeAdapter.get_workbench_status(...)`
- `ContextAccountingService.build_status_projection(...)`
- `RuntimeOutcomeDispatcher.resolve(...)`
- runtime outcome target resolution + continuation-directive classification before `SessionManager.apply_runtime_outcome(...)`

Why active:
- required for runtime status/CLI observability
- required to keep target-resolution and hold/continue policy interpretation outside the SessionManager core shell

---

## 3. Detached-by-default wiring (kept in-tree, short-circuited on default path)

These wires remain implemented but are no longer part of the default synchronous `runtime_core_minimal` path.

### 3.1 Knowledge surface (detached)

Previously attached through:

- `ObsidianKnowledgeService`
- `retrieve_knowledge_bundle(...)`
- knowledge preflight and vault metadata retrieval
- auxiliary fragment injection into provider payload build

Current state:
- code retained
- now routed behind `src/orbit/runtime/extensions/auxiliary_input.py`
- default provider payload path uses a detached/no-op collector configuration
- not invoked on canonical session submit path unless explicitly reattached

### 3.2 Memory augmentation surface (detached)

Previously attached through:

- memory fragment retrieval before provider payload build
- post-turn memory capture after assistant append

Current state:
- code retained
- pre-plan memory retrieval now lives behind `auxiliary_input.py`
- post-turn memory capture now lives behind `src/orbit/runtime/extensions/post_turn_observer.py`
- default minimal path keeps both detached / unbound

### 3.3 Capability/tool surface (detached)

Previously attached through:

- tool definitions in payload
- tool request normalization
- tool policy/governance closure
- approval continuation path

Current state:
- provider tool exposure is enabled on the active capability-attached path
- capability families activate through the capability composer / capability registry boundary
- tool requests now hand off through the capability surface and continue via provider-correlated tool-result reinjection rather than the older inline closure path

### 3.4 Audit/artifact/event surface (detached)

Previously attached through:

- `append_context_artifact_for_session(...)`
- `emit_session_event(...)`
- `_consume_pending_turn_snapshots(...)` artifact emission

Current state:
- methods retained
- default minimal core short-circuits artifact/event persistence
- pending snapshots are consumed without artifact emission on default path

---

## 4. Potential future re-blocking / accidental recoupling points

These are the highest-risk locations where future work could accidentally reintroduce blocking behavior onto the core path.

### 4.1 Provider payload build

File:
- `src/orbit/runtime/providers/openai_codex.py`

Risk:
- easiest place to reinsert knowledge/memory/auxiliary retrieval synchronously

Guardrail:
- do not directly call external retrieval/services from the default payload build path
- attach future auxiliary information only through an explicit pre-plan auxiliary boundary

### 4.2 SessionManager finalization

File:
- `src/orbit/runtime/core/session_manager.py`

Risk:
- tempting place to reinsert memory capture, audit sinks, post-turn enrichments, or tool/governance logic

Guardrail:
- treat `_finalize_session_plan(...)` as core terminalization only on the default path
- move non-core post-turn work behind observer/hook layers

### 4.3 Session metadata as a catch-all sink

Files:
- `SessionManager`
- `runtime_adapter`
- provider backend payload snapshots

Risk:
- metadata can easily become an unstructured cross-layer transport
- later extensions may silently depend on side-channel metadata writes

Guardrail:
- distinguish core metadata from surface projection metadata and detached observer metadata

### 4.4 Tool registry presence on the runtime path

Files:
- `RuntimeCapabilityComposer`
- `SessionManager.tool_registry`
- provider `build_tool_definitions()` / `normalize_events()`

Risk:
- tool-related code still exists near the runtime path even when detached by config/profile
- future reactivation could silently restore heavy closure logic to default chat

Guardrail:
- capability reattachment should happen through a named capability profile, not by toggling scattered booleans in the default path

---

## 5. Preferred future ingress points for new information/capability attachments

To preserve `runtime_core_minimal`, future information/capability integration should attach through explicit boundaries.

### 5.1 Pre-plan auxiliary input boundary

Purpose:
- allow external context/fragments to be added before payload assembly without directly hard-coding retrieval into the provider path

Current implementation status:
- real interface shell exists in `src/orbit/runtime/extensions/auxiliary_input.py`
- current detached collector already holds migrated knowledge/memory collection logic
- default runtime-core-minimal path uses the detached interface in disabled mode

Intended payload:
- auxiliary fragments
- provenance annotations
- attach policy decisions

Not for:
- synchronous sidecar discovery logic hidden inside the provider backend

### 5.2 Post-turn observer boundary

Purpose:
- allow non-core actions after turn completion without blocking canonical turn execution

Current implementation status:
- real interface shell exists in `src/orbit/runtime/extensions/post_turn_observer.py`
- current detached observer already holds migrated memory-capture logic
- default runtime-core-minimal path keeps the observer detached/unbound

Candidates:
- memory capture
- artifact sinks
- runtime event sinks
- analytics/telemetry
- audit logging

Not for:
- anything required for correctness of transcript/provider truth

### 5.3 Capability execution boundary

Purpose:
- reattach tools/MCP/governance without making them implicit in the default chat path

Candidates:
- explicit capability-enabled runtime profiles
- dedicated orchestration surface
- future capability session modes

Not for:
- hidden fallback from default runtime-core chat into tool closure

---

## 6. Current practical conclusion

As of 2026-04-09, the default `runtime_core_minimal` path is largely reduced to:

1. CLI/runtime-surface submit lifecycle
2. adapter bridge to SessionManager
3. SessionManager turn execution
4. provider payload build / transport / normalization
5. transcript + usage persistence
6. return to surface

This is the baseline to preserve.

Future extensions should be evaluated first as **surface attachments** or **observer hooks**, not as additions to the default synchronous core path.
