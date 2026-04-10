# ORBIT Interface Entrypoints Reference

## Purpose

This document captures the current ORBIT runtime-facing entrypoints, their parameters, return shapes, and intended usage posture.

It exists to support **isolated UI / CLI surface development** while the main runtime, MCP capability surface, and existing web inspector may be changing under parallel development by another agent.

The immediate goal is:
- read the current kernel/runtime entry surfaces
- preserve a stable design reference inside `docs/`
- let Web UI and CLI work proceed against a documented contract baseline
- delay direct runtime integration until the active kernel work is no longer being modified in parallel

## Current development posture

For now, the recommended implementation strategy is:
- **do not directly modify or depend on `web_inspector.py` as the main UI path**
- **do not couple new UI work directly into SessionManager internals yet**
- build new Web UI and CLI modules in isolation, using mock/view-model adapters derived from the contracts below
- later replace the mock adapter with a real adapter layer when the runtime side is stable again

---

# 1. Main runtime entry surface

## `SessionManager`

**Path:** `src/orbit/runtime/core/session_manager.py`

### Role
`SessionManager` is the active runtime mainline for ORBIT's current multi-turn session path.

From the current code and KB posture, it should be treated as the main runtime-facing kernel entry object for future integration work.

### Constructor

```python
SessionManager(*, store: OrbitStore, backend, workspace_root: str, enable_mcp_filesystem: bool = False)
```

#### Parameters
- `store: OrbitStore`
  - persistence backend used for sessions, messages, events, artifacts, and tool invocations
- `backend`
  - execution backend object
  - expected to support at least `plan(...)`, and optionally `plan_from_messages(...)`
- `workspace_root: str`
  - workspace boundary used for tools, path resolution, and runtime context
- `enable_mcp_filesystem: bool = False`
  - whether to bootstrap and register the local filesystem MCP tool family

#### Notes
- initializes a `ToolRegistry`
- may bootstrap filesystem MCP tools
- may inject the registry into the backend if the backend exposes `tool_registry`

---

# 2. Session lifecycle entrypoints

## `create_session(...)`

```python
create_session(*, backend_name: str, model: str, conversation_id: str | None = None) -> ConversationSession
```

### Purpose
Create a new ORBIT conversation session and persist it.

### Parameters
- `backend_name: str`
  - logical backend name, e.g. `openai-codex`
- `model: str`
  - model identifier associated with the session
- `conversation_id: str | None = None`
  - optional external conversation id; if omitted, one is generated

### Returns
- `ConversationSession`

### UI / CLI relevance
Useful for:
- new session creation flows
- session list bootstrap
- session metadata display

---

## `get_session(...)`

```python
get_session(session_id: str) -> ConversationSession | None
```

### Purpose
Fetch a stored session by id.

### Parameters
- `session_id: str`

### Returns
- `ConversationSession | None`

### UI / CLI relevance
Useful for:
- attach / resume flows
- route loading in Web UI
- session-detail fetch in CLI surface

---

## `list_messages(...)`

```python
list_messages(session_id: str) -> list[ConversationMessage]
```

### Purpose
Return transcript messages for a given session.

### Parameters
- `session_id: str`

### Returns
- `list[ConversationMessage]`

### UI / CLI relevance
Primary transcript source for:
- transcript panel
- chat view
- assistant / tool / policy / approval message rendering

---

## `append_message(...)`

```python
append_message(*, session_id: str, role: MessageRole, content: str, provider_message_id: str | None = None, metadata: dict | None = None) -> ConversationMessage
```

### Purpose
Append a message to a session transcript and update session timestamp.

### Parameters
- `session_id: str`
- `role: MessageRole`
- `content: str`
- `provider_message_id: str | None = None`
- `metadata: dict | None = None`

### Returns
- `ConversationMessage`

### UI / CLI relevance
Mostly runtime-internal today, but important as the canonical transcript append path.

---

# 3. Artifact / event entrypoints

## `append_context_artifact_for_session(...)`

```python
append_context_artifact_for_session(*, session_id: str, artifact_type: str, content: str, source: str) -> ContextArtifact | None
```

### Purpose
Persist a context artifact associated with the session's `conversation_id`.

### Parameters
- `session_id: str`
- `artifact_type: str`
- `content: str`
- `source: str`

### Returns
- `ContextArtifact | None`

### UI / CLI relevance
Potential future data source for:
- context panel
- payload snapshot panel
- runtime artifact browser
- operator inspection views

---

## `append_run_descriptor_for_session(...)`

```python
append_run_descriptor_for_session(*, session_id: str, descriptor: RunDescriptor) -> ContextArtifact | None
```

### Purpose
Persist the active `RunDescriptor` into session metadata and artifacts.

### Parameters
- `session_id: str`
- `descriptor: RunDescriptor`

### Returns
- `ContextArtifact | None`

### UI / CLI relevance
Useful for future “run contract / request context” inspection views.

---

## `emit_session_event(...)`

```python
emit_session_event(*, session_id: str, event_type: RuntimeEventType, payload: dict) -> ExecutionEvent | None
```

### Purpose
Emit a runtime event for the session's conversation/run.

### Parameters
- `session_id: str`
- `event_type: RuntimeEventType`
- `payload: dict`

### Returns
- `ExecutionEvent | None`

### UI / CLI relevance
Primary source for:
- event timeline view
- operator audit view
- runtime phase inspection

---

# 4. Main turn execution entrypoints

## `run_session_turn(...)`

```python
run_session_turn(*, session_id: str, user_input: str, descriptor: RunDescriptor | None = None) -> ExecutionPlan
```

### Purpose
Canonical session-turn executor.

This is the most important current runtime entrypoint for interactive use.

### Current contract
According to the code docstring:
- plain-text turns append assistant reply and return a final-text plan
- non-approval tool turns execute one governed tool closure inside the same turn
- approval-gated tool turns stop at a persisted waiting boundary
- approval continuation must resume through `resolve_session_approval(...)`

### Parameters
- `session_id: str`
- `user_input: str`
- `descriptor: RunDescriptor | None = None`
  - optional explicit run contract snapshot for the turn

### Returns
- `ExecutionPlan`

### UI / CLI relevance
This is the likely future adapter target for:
- chat send action
- turn submit action
- CLI `chat send`
- Web UI message composer submit

### Important caution
Do not bind the first isolated UI implementation directly to all of SessionManager’s side effects yet.
Instead, treat this as the **future runtime adapter boundary**.

---

## `resolve_session_approval(...)`

```python
resolve_session_approval(*, session_id: str, approval_request_id: str, decision: str, note: str | None = None) -> ExecutionPlan
```

### Purpose
Resolve a pending approval request and resume the turn.

### Parameters
- `session_id: str`
- `approval_request_id: str`
- `decision: str`
  - expected values in current code: `approve` or `reject`
- `note: str | None = None`

### Returns
- `ExecutionPlan`

### UI / CLI relevance
Future adapter target for:
- approval modal actions
- approve / reject buttons
- CLI approval commands

---

## `list_open_session_approvals(...)`

```python
list_open_session_approvals() -> list[dict]
```

### Purpose
Return session-scoped pending approvals.

### Returns
- `list[dict]`

### UI / CLI relevance
Useful for:
- global approvals drawer
- operator approval queue
- CLI approval list command

---

## `reauthorize_tool_path(...)`

```python
reauthorize_tool_path(*, session_id: str, tool_name: str, note: str | None = None, source: str = "runtime_entry") -> dict
```

### Purpose
Record structured reauthorization for a tool path after earlier rejection/authority gating.

### Parameters
- `session_id: str`
- `tool_name: str`
- `note: str | None = None`
- `source: str = "runtime_entry"`

### Returns
- `dict`

### UI / CLI relevance
Potential future operator/governance action surface.
Not necessarily first-wave UI scope.

---

# 5. Tool / filesystem-related runtime helpers

These are important for understanding current runtime semantics, but they are **not recommended as first-wave direct UI coupling targets**.
They are better treated as underlying kernel behavior that later surfaces through normalized view models.

## Notable helper methods
- `execute_tool_request(...)`
- `maybe_block_write_for_grounding(...)`
- `maybe_make_filesystem_unchanged_result(...)`
- `filesystem_grounding_status_for_path(...)`
- `filesystem_write_readiness_for_path(...)`
- `record_filesystem_read_state(...)`
- `append_tool_result_message(...)`

### Design implication
The isolated UI should not directly model itself around these helper methods.
Instead, it should consume normalized outputs such as:
- transcript messages
- runtime events
- tool invocation records
- session metadata summaries

---

# 6. Execution backend boundary

## `ExecutionBackend`

**Path:** `src/orbit/runtime/execution/backends.py`

### Interface

```python
class ExecutionBackend(ABC):
    backend_name: str = "abstract"

    @abstractmethod
    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        ...
```

### Purpose
Small backend boundary between coordinator/session runtime and execution source.

### Current design meaning
- runtime flow remains governed by ORBIT runtime
- provider/backend logic stays outside the coordinator
- backend returns a bounded `ExecutionPlan`

### UI / CLI relevance
This is more of a kernel seam than a UI seam, but it matters because it defines what the runtime receives from providers.

---

## `DummyExecutionBackend.plan(...)`

```python
def plan(self, descriptor: RunDescriptor) -> ExecutionPlan
```

### Purpose
Deterministic dummy execution plan generation.

### Relevance
Useful for isolated mock adapters and UI development if we want runtime-shaped fake data.

---

## `SshVllmExecutionBackend.plan(...)`

```python
def plan(self, descriptor: RunDescriptor) -> ExecutionPlan
```

### Status
Placeholder / not implemented.

---

# 7. Hosted provider backend currently in use

## `OpenAICodexExecutionBackend`

**Path:** `src/orbit/runtime/providers/openai_codex.py`

### Constructor

```python
OpenAICodexExecutionBackend(
    config: OpenAICodexConfig | None = None,
    repo_root: Path | None = None,
    workspace_root: Path | None = None,
    tool_registry: ToolRegistry | None = None,
)
```

### Main public methods

#### `plan(...)`

```python
plan(descriptor: RunDescriptor) -> ExecutionPlan
```

Wraps the descriptor as a single user message and forwards into history-aware logic.

#### `plan_from_messages(...)`

```python
plan_from_messages(messages: list[ConversationMessage], *, session: ConversationSession | None = None) -> ExecutionPlan
```

### Purpose
Current main provider-facing planning method for SessionManager-backed chat.

### Parameters
- `messages: list[ConversationMessage]`
- `session: ConversationSession | None = None`

### Returns
- `ExecutionPlan`

### Important side effects
If `session` is provided, current code writes:
- `session.metadata["last_provider_payload"]`
- pending context assembly snapshot
- pending provider payload snapshot

### UI relevance
These side effects are exactly why the existing inspector can show:
- payload view
- context assembly view

For isolated development, these should be treated as **future inspectable adapter data**, not as an invitation to reuse the current inspector implementation directly.

---

# 8. Current CLI entry surfaces

## Runtime-first terminal mainline

**Primary path:** `src/orbit/interfaces/pty_runtime_cli.py`

### Posture
This is now the authoritative terminal entry surface for ORBIT.
The older `src/orbit/cli.py` and `src/orbit/cli_session.py` entrypoints were removed after the runtime-first PTY CLI absorbed their primary interactive responsibilities.

### Primary script entrypoints
- `orbit`
- `orbit-session`
- `orbit-runtime-workbench`

All three now point at:
- `orbit.interfaces.pty_runtime_cli:browse_runtime_cli`

### Runtime integration helper path
SessionManager-backed runtime wiring used to live behind `cli_session.py` helpers.
It now lives in:
- `src/orbit/interfaces/runtime_adapter.py`

Key helpers:
- `build_codex_session_manager_for_profile(...)`
- `get_pending_session_approval(...)`
- `resolve_pending_session_approval(...)`

### Recommendation
Build all new terminal UX, session control, and approval-flow work on the runtime-first PTY CLI and its adapter/router layers rather than reviving removed legacy entrypoints.

A recent carryover checklist for lessons learned during governed MCP CLI debugging now lives at:
- `docs/pty-runtime-cli-migration-carryover-checklist-2026-04-04.md`

---

## Historical note

The removed legacy paths:
- `src/orbit/cli.py`
- `src/orbit/cli_session.py`

should be treated as historical documentation references only when reading older notes or commits.

### Purpose
Run a minimal SessionManager-mainline chat REPL.

### Current command grammar inside the REPL
Runtime-scope commands:
- `/sessions`
- `/attach <session_id>`
- `/new`
- `/clear-all`
- `/help`
- `/exit`

Session-scope commands:
- `/show`
- `/state`
- `/events`
- `/clear`
- `/detach`

### Design implication
This is a strong reference for the future isolated CLI module, but the new CLI should still be developed as a new module rather than by incrementally mutating this file during parallel runtime work.

---

# 9. Existing web inspector surface

## `serve(...)`

**Path:** `src/orbit/web_inspector.py`

```python
serve(host: str = "127.0.0.1", port: int = 8789, open_browser: bool = False) -> None
```

### Purpose
Run the current local web inspector.

### Parameters
- `host: str = "127.0.0.1"`
- `port: int = 8789`
- `open_browser: bool = False`

### Current characteristics
- SQLite-backed read surface
- session sidebar
- transcript tab
- payload tab
- context tab
- tool calls tab
- right-side panels for metadata / events / artifacts / summary

### Recommendation
This file is useful as a **reference inventory of inspectable data categories**, but should not be treated as the direct implementation base for the new isolated UI module while another agent may also touch web inspector and runtime surfaces.

Instead, extract from it the data/view concepts:
- session list
- transcript view
- payload view
- context view
- tool call view
- metadata view
- events view
- artifacts view

---

# 10. Current contract objects relevant to UI / CLI design

## `RunDescriptor`

**Path:** `src/orbit/runtime/core/contracts.py`

```python
RunDescriptor(
    run_id: str,
    session_key: str,
    conversation_id: str,
    runtime_family: str = "dummy",
    workspace: WorkspaceDescriptor,
    agent: AgentDescriptor = AgentDescriptor(),
    model: ModelDescriptor = ModelDescriptor(),
    execution: ExecutionDescriptor = ExecutionDescriptor(),
    tools: ToolingDescriptor = ToolingDescriptor(),
    delivery: DeliveryDescriptor = DeliveryDescriptor(),
    provenance: ProvenanceDescriptor = ProvenanceDescriptor(),
    user_input: str,
    dummy_scenario: str = "tool_then_finish",
)
```

### Purpose
Primary cross-layer execution contract.

### UI / CLI relevance
Future advanced inspection / request preview / run contract visualization.

---

## `ToolRequest`

**Path:** `src/orbit/runtime/execution/contracts/plans.py`

```python
ToolRequest(
    tool_name: str,
    input_payload: dict = {},
    requires_approval: bool = False,
    side_effect_class: str = "safe",
)
```

### Purpose
Bounded tool request emitted by an execution backend.

### UI / CLI relevance
Primary shape for:
- approval request rendering
- tool call preview
- tool activity summary

---

## `ExecutionPlan`

**Path:** `src/orbit/runtime/execution/contracts/plans.py`

```python
ExecutionPlan(
    source_backend: str,
    plan_label: str,
    final_text: str | None = None,
    tool_request: ToolRequest | None = None,
    should_finish_after_tool: bool = True,
    failure_reason: str | None = None,
)
```

### Purpose
Backend-neutral bounded execution result.

### UI / CLI relevance
Very important as a future adapter return shape for:
- send-turn result handling
- approval wait state
- final text closure
- failure state rendering

---

# 11. Recommended isolated surface design baseline

## Web UI module should initially model
- session list
- session detail shell
- transcript panel
- runtime event panel
- metadata / context / payload drawers or tabs
- approval queue surface
- tool activity surface
- empty / waiting / failed / detached states

## CLI module should initially model
- `session list`
- `session show`
- `session events`
- `session state`
- `chat attach`
- `chat new`
- `chat send`
- `approval list`
- `approval approve`
- `approval reject`

## Adapter rule
Both Web UI and CLI should depend on a future adapter interface like:
- `list_sessions()`
- `get_session(session_id)`
- `list_messages(session_id)`
- `list_events(session_id)`
- `list_artifacts(session_id)`
- `list_tool_calls(session_id)`
- `run_turn(session_id, user_input)`
- `list_open_approvals()`
- `resolve_approval(...)`

That adapter can be mocked first, then later backed by SessionManager/store/runtime once kernel contention is over.

---

# 12. What to avoid right now

To preserve parallel development safety, avoid:
- editing `src/orbit/web_inspector.py` as the main workbench path right now
- tightly coupling new UI component structure to current SQLiteStore internals
- directly binding view semantics to low-level helper methods like grounding helpers
- mutating SessionManager just to satisfy provisional UI needs
- treating the current inspector HTML implementation as the future architecture

---

# 13. Summary

The current safest path is:
1. treat `SessionManager` as the future runtime integration boundary
2. treat `RunDescriptor`, `ToolRequest`, and `ExecutionPlan` as the main contract anchors
3. treat `cli_session.py` and `web_inspector.py` as reference surfaces, not direct bases
4. build new Web UI and CLI modules in isolation against mock adapters
5. integrate only after the parallel runtime / MCP / tools capability work settles
