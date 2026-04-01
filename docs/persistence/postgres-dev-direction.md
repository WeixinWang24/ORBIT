# ORBIT PostgreSQL development direction

## Current status

ORBIT now has:
- a stable persistence interface (`OrbitStore`)
- a bootstrap SQLite implementation (`SQLiteStore`)
- a first PostgreSQL implementation (`PostgresStore`)
- backend selection through `ORBIT_STORE_BACKEND`

## Current default

The default backend remains `sqlite` because:
- SQLite is an acceptable bootstrap/default local backend in v0
- notebook-first iteration speed currently matters more than forcing service setup
- the local machine does not yet expose a ready PostgreSQL server/client toolchain to ORBIT commands

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

## Why the default has not switched yet

The code path is ready, but the local machine currently does not expose:
- `psql`
- `postgres`
- `pg_ctl`

So the repository should not pretend PostgreSQL is locally runnable before the actual service path exists.
