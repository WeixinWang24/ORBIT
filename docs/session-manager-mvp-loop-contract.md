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

This means:
- transcript/history is the primary visible truth of what happened in a session
- session-local control state exists to make current runtime control conditions explicit, not to replace transcript truth
- runtime events remain a coarse observational shell around transcript/session truth rather than becoming the canonical source of conversational history

## Truth layers

### Transcript truth

The session transcript is the fine-grained visible truth.

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

Currently validated event sequences include:
- plain text: `run_started`
- non-approval tool closure: `run_started -> tool_invocation_completed`
- approval wait: `run_started -> approval_requested`
- approval approve-resume: `run_started -> approval_requested -> approval_granted -> tool_invocation_completed`
- approval reject-resume: `run_started -> approval_requested -> approval_rejected`

## Current scope note

This contract describes the active SessionManager-centered MVP loop, not the retired historical OrbitCoordinator scaffold.
