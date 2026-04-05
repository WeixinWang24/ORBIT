# ORBIT PostgreSQL schema notes

## First-version storage strategy

The first ORBIT PostgreSQL implementation uses a hybrid pattern:

- a small set of explicit indexed columns for ordering and filtering
- one canonical `JSONB` payload column named `data` for each domain object

This is deliberate.

## Why JSONB-first

ORBIT's core runtime ontology is still stabilizing.
A JSONB-first strategy allows the repository to:
- preserve current domain object shape
- avoid premature relational decomposition
- keep runtime and persistence evolution decoupled
- support future migration once query pressure becomes clearer

## Current tables

- `tasks`
- `runs`
- `run_steps`
- `events`
- `tool_invocations`
- `approval_requests`
- `approval_decisions`
- `context_artifacts`
- `sessions`
- `session_messages`
- `managed_processes`

## Query-critical columns

Examples of explicit columns in the first version:
- ids
- timestamps
- run/task relationships
- step ordering
- status fields
- event type
- tool name

## Architectural note

This schema should be treated as the first operational PostgreSQL layer, not the final database design.
It is optimized for:
- early inspectability
- continuity with the current Pydantic domain model
- reduced migration pressure during v0/v1
