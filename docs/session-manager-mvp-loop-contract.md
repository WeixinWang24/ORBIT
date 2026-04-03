# SessionManager MVP Loop Contract

This note captures the currently validated single-turn runtime contract for ORBIT's active SessionManager-centered mainline.

## Canonical turn boundaries

### `run_session_turn(...)`

`run_session_turn(...)` is the canonical first-turn executor.

It currently has three valid bounded outcomes:

1. **Plain-text completion**
   - appends the user message
   - plans from the session transcript
   - appends the assistant final message
   - returns a final-text `ExecutionPlan`

2. **Non-approval governed tool completion**
   - appends the user message
   - plans a tool request that does not require approval
   - executes the tool inside the same turn
   - appends the transcript-visible tool result
   - replans once
   - appends the assistant continuation/final message
   - returns the bounded post-tool `ExecutionPlan`

3. **Approval waiting boundary**
   - appends the user message
   - plans a tool request that requires approval
   - persists session-local pending approval truth
   - emits `approval_requested`
   - appends the transcript-visible approval request
   - returns a waiting `ExecutionPlan`

### `resolve_session_approval(...)`

`resolve_session_approval(...)` is the canonical resumed-turn executor for approval-gated turns.

It currently has two valid bounded outcomes:

1. **Approve-resume**
   - clears pending approval
   - emits `approval_granted`
   - appends the approval decision message
   - executes the governed tool
   - appends the transcript-visible tool result
   - replans once
   - appends the assistant continuation/final message
   - returns the bounded post-tool `ExecutionPlan`

2. **Reject-resume**
   - clears pending approval
   - emits `approval_rejected`
   - appends the approval decision message
   - builds rejection continuation context
   - replans without tool execution
   - appends the assistant continuation/final message
   - returns the bounded post-rejection `ExecutionPlan`

## Architectural statement

ORBIT's active session management posture is now transcript-canonical session management.

A related rule now also applies: model-world is not runtime-world.
Provider-model self-description about schemas, roles, or tool behavior is not authoritative runtime truth; session/runtime boundaries must be determined from actual runtime contracts, payload projection, persisted state, events, and observation artifacts.

This means:
- transcript/history is the primary visible truth of what happened in a session
- session-local control state exists to make current runtime control conditions explicit, not to replace transcript truth
- runtime events remain a coarse observational shell around transcript/session truth rather than becoming the canonical source of conversational history

## Truth layers

### Transcript truth

The session transcript is the fine-grained visible truth.

For prompt/context assembly, transcript may later be transformed into a derived history context element, but the canonical transcript itself remains the source-of-truth visible conversation record.

It must preserve whether:
- a tool was only requested
- a tool was executed
- approval was granted or rejected
- continuation happened after rejection

### Session state truth

Session-local runtime truth currently lives in:
- `session.metadata["pending_approval"]`
- `session.governed_tool_state`

This is the explicit session-scoped control state for the MVP loop.

### Runtime event shell

Runtime events are the coarse observational shell around the transcript/session truth.

### Snapshot observation rule

Context assembly snapshots and provider payload snapshots are derived observation artifacts for turn inspection.
They are not canonical transcript/history truth and they do not replace canonical runtime control state.
The runtime should treat them as SessionManager-owned debugging/inspection records rather than letting provider/backend layers directly define stable session truth through snapshot side channels.

Currently validated event sequences include:
- plain text: `run_started`
- non-approval tool closure: `run_started -> tool_invocation_completed`
- approval wait: `run_started -> approval_requested`
- approval approve-resume: `run_started -> approval_requested -> approval_granted -> tool_invocation_completed`
- approval reject-resume: `run_started -> approval_requested -> approval_rejected`
- policy-denied / environment-denied tool path: `run_started -> run_failed`

## MCP filesystem minimal re-entry note

The first Python-first MCP filesystem re-entry slice is now validated on the active SessionManager mainline.

Key current rules:
- native tools are explicitly source-tagged (`native__read_file`, `native__write_file`)
- MCP-exposed tools keep canonical/original names (for example `read_file`)
- the local filesystem MCP server keeps the same workspace-relative canonical path discipline as native tools
- provider payload exposure and execution truth now share one ToolRegistry instead of rebuilding parallel registries inside the provider adapter
- policy-denied MCP tool requests now persist failed `ToolInvocation` records so tool-call inspection surfaces can show denied/failed attempts as first-class runtime truth

Current validated MCP filesystem v0 behaviors include:
- direct MCP `read_file` invocation success
- SessionManager-bounded same-turn MCP safe-read closure success
- path-escape denial at the policy/environment boundary before tool execution
- transcript / events / tool-invocation persistence / inspector-facing snapshots all agreeing on the same runtime truth for the validated slice

## Current scope note

This contract describes the active SessionManager-centered MVP loop, not the retired historical OrbitCoordinator scaffold.
