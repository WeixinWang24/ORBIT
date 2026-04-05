# ORBIT PostgreSQL development direction

## Current status

ORBIT now has:
- a stable persistence interface (`OrbitStore`)
- a bootstrap SQLite implementation (`SQLiteStore`)
- a first PostgreSQL implementation (`PostgresStore`)
- backend selection through `ORBIT_STORE_BACKEND`

## Current default

The default backend is now `postgres` for the active persistence phase.

Why this changed:
- transcript/history and memory persistence are now treated as primary architecture work rather than distant migration work
- the repository should evolve against the intended long-term persistence boundary now, not only after the phase ends
- SQLite remains useful, but only as a bounded fallback when PostgreSQL is temporarily unavailable in local development

## Switching to PostgreSQL later

When a PostgreSQL database is available, set environment variables such as:

```bash
export ORBIT_STORE_BACKEND=postgres
export ORBIT_PG_HOST=127.0.0.1
export ORBIT_PG_PORT=5432
export ORBIT_PG_DBNAME=orbit
export ORBIT_PG_USER=orbit
export ORBIT_PG_PASSWORD=orbit
```

Then run ORBIT from the `Orbit` Conda environment.

## Fallback rule

If PostgreSQL is selected but cannot be reached at runtime, ORBIT currently falls back to SQLite automatically.

This fallback is intentional for the current phase:
- PostgreSQL is the primary development target
- SQLite preserves low-friction local bring-up, notebook demos, and temporary offline development
- new persistence design should avoid SQLite-only assumptions even when fallback is exercised
