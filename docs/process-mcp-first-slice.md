# Process MCP First Slice

## Status

Implemented. This document describes the external capability shape and first-slice
boundaries. For implementation truth — including persistence model, runner contract,
and lifecycle truth precedence — see `process-task-backed-first-slice-design.md`.

## Goal

A bounded process/job MCP family for long-running local commands that should not be
overloaded onto `run_bash`.

This family covers process lifecycle management:
- start
- read output
- wait
- terminate

It is intentionally separate from one-shot shell execution.

## External canonical tools

- `start_process`
- `read_process_output`
- `wait_process`
- `terminate_process`

## Internal structure

The implementation has three internal components:

1. **Persistent process registry (`ManagedProcess` in `OrbitStore`)**
   - maps `process_id` to persisted process state
   - stores cwd, command, started_at, status, exit_code, stdout/stderr paths, byte offsets
   - survives across service-instance boundaries (cross-call continuity guaranteed by store)

2. **Persisted output surfaces (stdout/stderr files)**
   - output goes directly to `{process_id}.stdout.log` and `{process_id}.stderr.log`
   - these are first-class persisted surfaces, not incidental side artifacts
   - byte offsets stored in `ManagedProcess` enable incremental reads across any service instance

3. **Runner-backed lifecycle model with runner status file**
   - process runs under `managed_process_runner.py`
   - runner writes `{process_id}.status.json` atomically on status transitions
   - runner status file is the PRIMARY source of terminal lifecycle truth
   - states: `running | completed | failed | killed`

## Lifecycle truth precedence

This is an explicit invariant of the implementation:

1. **Runner status file** (primary): written by `managed_process_runner.py` directly.
   Survives service-instance boundaries. Checked first in all terminal-state decisions.
2. **PID polling** (fallback only): used when the runner status file is absent or not yet
   terminal. Must not override a confirmed runner terminal status.
3. **Store record** (context): reflects the last reconciled view. Always updated to match
   the highest-precedence truth found.

## Termination semantics

Termination is a lifecycle transition request, not an optimistic local overwrite:
1. Send SIGTERM to the process group (runner + child command).
2. Wait for the runner status file to confirm terminal state (primary truth).
3. If no confirmation within the escalation window, escalate to SIGKILL.
4. Reconcile store from runner status file. Fall back to writing `killed` locally
   only if the runner status file is absent or incomplete.

## First-slice boundaries

- no PTY
- no interactive stdin session
- workspace-scoped cwd
- shell-launched command (login shell, non-interactive)
- approval-first governance for the family
- bounded output reads with persisted byte offsets
- explicit process IDs, not implicit session attachment
- no stall detection or interactive-prompt watchdog
- no terminal notification/event emission when a process completes
- no agent-scoped cleanup sweep

## Relationship to `run_bash`

- `run_bash` remains one-shot and bounded
- process MCP family handles long-lived/background execution
- do not evolve `run_bash` into a job-control surface

## Current viability

The first slice is viable. Validated that:
- a process can be started and its handle persists across service-instance boundaries
- output can be read incrementally using persisted byte offsets
- the caller can wait for completion even without a live Popen handle
- the caller can terminate a running process with SIGTERM + SIGKILL escalation
- a fresh service instance recovers terminal truth from the runner status file
- the lifecycle works through the real ORBIT runtime/MCP surface

## Remaining first-slice limitations

- No `list_processes` / `get_process` tool exposed to the model
- No stall watchdog (a hanging interactive process silently consumes timeout)
- No completion notification; model must actively poll
- SQLite `delete_session` does not delete managed_processes (intentional, separate lifecycle)
- Postgres `delete_session` does delete managed_processes (inconsistency, not yet resolved)
- SIGKILL escalation requires the runner process to be a direct child; orphaned processes
  that have re-parented to PID 1 may not receive the process-group kill
