# Process Task-Backed MCP Family Note

## Why this note exists

ORBIT initially explored a process MCP first slice using a stateless stdio MCP server with an in-memory process registry.

Real MCP testing showed that this substrate is not sufficient for a true process-lifecycle capability.
The current stdio MCP server pattern works well for stateless tools such as filesystem mutation and one-shot bash execution, but it does not provide the continuity needed for cross-call process lifecycle operations.

## Key discovery

A process-lifecycle family needs continuity across calls for:
- process handles
- output offsets
- status transitions
- termination and cleanup

A short-lived or per-call stdio server with in-memory state cannot reliably provide that continuity.

## Updated design direction

Instead of treating process lifecycle as a plain stateless MCP family, ORBIT should treat it as a **task-backed persistent capability family**.

This means the internal model should look more like:
- persistent process/task registry
- persistent output tracking
- explicit lifecycle state model
- stop/wait/read operations against persistent task identity

This direction aligns better with the strongest Claude Code references:
- `LocalShellTask`
- `TaskOutput`
- `TaskOutputTool`
- `TaskStopTool`
- task framework state/update/notification flow

## Likely external tool shape

The user-facing capability may still eventually expose tools that feel like:
- `start_process`
- `read_process_output`
- `wait_process`
- `terminate_process`

But those tools should be backed by persistent task/process identity, not a transient in-memory server-local map.

An alternative first external contract may be even more explicit:
- `create_process_task`
- `read_process_task_output`
- `wait_process_task`
- `stop_process_task`

## First implementation rule

Do not continue investing in a process MCP server that assumes server-local in-memory registry continuity unless the transport/runtime contract itself guarantees server persistence.

Until that guarantee exists, process lifecycle should be designed on top of persistent task-backed state.

## Practical next step

The next real first slice should define:
1. persistent registry model
2. output storage model
3. task lifecycle states
4. minimal tool/API contract for start / read / wait / stop

That should happen before further implementation of the naive transient process MCP prototype.
