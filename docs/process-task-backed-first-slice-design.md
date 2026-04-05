# Process Task-Backed First Slice Design

## Status

**Implemented.** This document reflects the current implementation truth.
Design intent is preserved; post-implementation reality is annotated inline.

---

## Why this approach exists

This note replaces the naive transient process MCP prototype as the primary design direction.

The earlier discovery stands:
- a stateless stdio MCP server with only in-memory registry state is not a valid substrate
  for true process lifecycle management
- process lifecycle requires cross-call continuity
- therefore ORBIT must ground this family in persistent task/process state

---

## Design principle

Treat process lifecycle as a **task-backed persistent capability**.

This means:
- the runtime/store layer is the primary continuity boundary
- MCP/server code is an execution surface, not the sole owner of process identity
- process/job state survives across multiple tool calls within a session lifecycle

---

## Lifecycle truth precedence (explicit invariant)

ORBIT process lifecycle has an explicit truth-precedence order. All terminal-state
decisions must respect this hierarchy:

1. **Runner status file** (PRIMARY truth):
   Written atomically by `managed_process_runner.py` to `{process_id}.status.json`.
   Populated on process start (status=running), on SIGTERM/SIGINT receipt (status=killed),
   and on normal exit (status=completed or failed). Includes `exit_code`, `signal`, and
   `written_at` timestamp. Survives across service-instance boundaries unconditionally.

2. **PID polling** (FALLBACK only):
   Used only when the runner status file is absent or does not yet show a terminal state.
   Less reliable across service-instance boundaries (requires direct child relationship
   for `os.waitpid`; non-child PIDs can only be existence-probed via `os.kill(pid, 0)`).
   Results from pid polling must **not** override a confirmed runner terminal status.

3. **Store record** (CONTEXT):
   The persisted `ManagedProcess` in `OrbitStore` reflects the last reconciled view.
   Always updated to match the highest-precedence truth found during refresh.

This ordering is implemented in `ProcessService.refresh_process` and enforced throughout.
It must not be weakened without deliberate revision of this document.

---

## Persisted output surfaces (first-class correctness concern)

`stdout_path` and `stderr_path` in `ManagedProcess` are not incidental side artifacts.
They are first-class persisted output surfaces that must be treated as such:

- output files are written directly by the runner (no in-memory buffering through service)
- byte offsets (`stdout_offset`, `stderr_offset`) are persisted in the `ManagedProcess` store record after every `read_output_delta` call
- output continuity across service instances is guaranteed by these persisted offsets
- a new `ProcessService` instance can resume reading from the correct position without any coordination with the original Popen handle

Output continuity is a correctness requirement for process-family reattachment, not a
nice-to-have performance detail.

---

## Termination semantics (lifecycle transition request, not optimistic overwrite)

Previous implementation: `terminate_process` sent SIGTERM then immediately wrote
`status=killed` to the store (optimistic local overwrite), without waiting for
runner confirmation.

Current implementation treats termination as a lifecycle transition REQUEST:

1. Send `SIGTERM` to the process group (runner + child command via `os.killpg`).
2. Poll the runner status file until it confirms a terminal state (primary truth) or
   the escalation timeout expires (default 3 seconds).
3. If the runner has not confirmed, escalate to `SIGKILL`.
4. Wait briefly for SIGKILL confirmation from the runner status file (1 second).
5. Call `refresh_process` to reconcile the store from runner truth.
   Only if the runner status file is absent/incomplete, fall back to writing `killed`
   locally as a last resort.

This ensures:
- the store reflects persisted runner truth, not a speculative local claim
- a process that completed naturally just before the signal is recorded as `completed`, not `killed`
- SIGKILL escalation is available for processes that ignore SIGTERM

---

## First-slice external contract

- `start_process`
- `read_process_output`
- `wait_process`
- `terminate_process`

Internally, these resolve through persistent task/process identity rather than
ephemeral server-only identity. The MCP server is intentionally stateless between
calls; all continuity is carried by the store + runner status files + output files.

---

## Internal components (implemented)

### 1. Persistent process registry record (`ManagedProcess`)

Fields:
- `process_id` — `proc_<12hex>`
- `session_id` — owning session
- `command` — original command string
- `cwd` — resolved workspace-relative working directory
- `status` — `running | completed | failed | killed`
- `pid` — runner PID (also the process group leader PID)
- `started_at`, `updated_at`, `ended_at`
- `exit_code`
- `stdout_path`, `stderr_path` — persisted output surface paths
- `status_path` — runner status file path (primary lifecycle truth)
- `stdout_offset`, `stderr_offset` — persisted byte read positions
- `metadata`

Stored via `OrbitStore` (SQLite or Postgres). Not deleted on session cleanup in SQLite
(process lifecycle is a separate lifecycle concern); Postgres currently does delete
on session cleanup — a known inconsistency to resolve.

### 2. Output storage model

Files: `{workspace}/.orbit_process/{process_id}.stdout.log` and `.stderr.log`.
Written in append mode by the runner. Read via byte-offset delta in `ProcessService`.
Offsets persisted to store after every read. No in-memory accumulation.

### 3. Runner / status-file reattachment contract

`managed_process_runner.py` is spawned with `start_new_session=True` (becomes its
own process group leader). It writes the status file:
- at startup (`status=running`)
- on `SIGTERM`/`SIGINT` receipt (`status=killed`)
- on natural exit (`status=completed` or `status=failed`)

Each write includes a `written_at` timestamp. Any later `ProcessService` instance can
read this file to recover terminal lifecycle truth without needing the original Popen handle.

---

## Success condition (updated)

The first slice is viable when — **all of the following verified in tests**:

- `start_process` returns a process handle that remains valid across later calls ✓
- `read_process_output` can retrieve deltas across calls via persisted offsets ✓
- `wait_process` observes real status changes (with and without live handle) ✓
- `terminate_process` reconciles with runner truth, not just optimistic local write ✓
- a fresh service instance (no live handles) recovers terminal process truth from the runner
  status file ✓
- output delta continuity is preserved across service-instance boundaries ✓
- fallback pid-polling behavior is graceful when runner status file is absent ✓
- the whole lifecycle works through the real ORBIT runtime/MCP surface without relying on
  accidental server persistence ✓

---

## Remaining first-slice limitations (not regressions, bounded intentionally)

- No `list_processes` / `get_process` tool exposed to the model
- No stall watchdog or interactive-prompt detection
- No completion notification; model must actively poll
- No agent-scoped cleanup sweep on session end
- SIGKILL may not reach processes that have re-parented beyond the original process group
- SQLite / Postgres inconsistency in `delete_session` behavior for managed_processes
- No eviction or cleanup policy for accumulated output files in `.orbit_process/`

---

## First implementation warning (still applies)

Do not treat a short-lived stdio MCP server's in-memory `_PROCESSES` map as authoritative
process truth. That approach has been falsified by real MCP testing. The persisted runner
status file + OrbitStore are the correct continuation boundary.
