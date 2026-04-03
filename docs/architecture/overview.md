# ORBIT architecture notes

## Current decisions

- Language/runtime direction: Python-first
- V0 interaction surfaces: Jupyter Notebook plus local web inspector
- V1 interaction direction: migrate/adapt Vio Dashboard frontend
- Default development environment: Conda environment `Orbit`
- Long-term primary persistence direction: PostgreSQL
- Current default local/bootstrap backend in v0: SQLite
- V0 memory posture: no full memory subsystem yet; use explicit context artifacts and simple context engineering
- `RunDescriptor` should become the primary cross-layer execution contract
- `SessionManager` is the active runtime mainline host for the MVP session agent loop
- `run_session_turn(...)` is the canonical first-turn bounded executor; `resolve_session_approval(...)` is the canonical resumed-turn bounded executor for approval-gated turns
- Runtime event model should remain separate from UI message rendering structures
- Control/state persistence and transcript/history persistence should remain conceptually distinct
- MCP-exposed tool names should remain canonical/original where possible; runtime-native tools carry explicit `native__` source tagging
- Provider payload tool exposure should use the same already-assembled ToolRegistry truth as execution rather than rebuilding parallel registries

## ADR anchors

The following ADRs currently define ORBIT's most important early runtime boundaries:
- `ADR-0001` — Python-first, notebook-first, Conda `Orbit`, persistence staging
- `ADR-0002` — `RunDescriptor` as cross-layer execution contract
- `ADR-0003` — runtime event model separate from UI message model
- `ADR-0004` — transcript and store separation

## Important boundary note

The current SQLite-backed `src/orbit/db.py` is bootstrap infrastructure only.
It exists to support early runtime bring-up and should later be replaced or wrapped by PostgreSQL-backed persistence while keeping core domain object boundaries stable.

## Current emphasis

- validate governance-first runtime shape before broadening providers
- keep notebook inspection surfaces first-class
- maintain store/runtime separation
- prefer explicit boundaries over magic orchestration
- keep provider/auth/transport concerns grouped by module so live-backend growth stays readable
- keep transcript truth, session control state, and runtime-event shell explicitly separated even when one turn is closure-complete

## Current source grouping

- `runtime/providers/` groups provider-family implementations
- `runtime/auth/` groups OAuth/auth store helpers
- `runtime/transports/` groups HTTP/SSE/SSH tunnel helpers
- notebook demos remain split by provider path rather than merged into one ambiguous helper surface
