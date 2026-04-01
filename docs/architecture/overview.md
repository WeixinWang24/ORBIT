# ORBIT architecture notes

## Current decisions

- Language/runtime direction: Python-first
- V0 interaction surface: Jupyter Notebook
- V1 interaction direction: migrate/adapt Vio Dashboard frontend
- Default development environment: Conda environment `Orbit`
- Long-term primary persistence direction: PostgreSQL
- Current default local/bootstrap backend in v0: SQLite
- V0 memory posture: no full memory subsystem yet; use explicit context artifacts and simple context engineering
- `RunDescriptor` should become the primary cross-layer execution contract
- Runtime event model should remain separate from UI message rendering structures
- Control/state persistence and transcript/history persistence should remain conceptually distinct

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

## Current source grouping

- `runtime/providers/` groups provider-family implementations
- `runtime/auth/` groups OAuth/auth store helpers
- `runtime/transports/` groups HTTP/SSE/SSH tunnel helpers
- notebook demos remain split by provider path rather than merged into one ambiguous helper surface
