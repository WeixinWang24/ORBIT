# ORBIT

ORBIT is a Python-first, governance-oriented personal agent workbench.

## Current scope

This repository currently contains a Phase 0/1 skeleton for:
- typed core domain objects
- explicit runtime coordination
- structured event logging
- temporary bootstrap persistence with PostgreSQL as the architectural direction
- narrow initial tool boundaries
- notebook-friendly projection helpers

## Philosophy

ORBIT is being built as:
- a research artifact
- a teaching/demonstration instrument
- a personal productivity workbench

It is not currently intended to be:
- a multitenant platform
- a plugin marketplace
- a maximal-autonomy agent system
- a broad channel integration hub

## Quick start

Use the dedicated Conda environment for ORBIT work.

```bash
cd /Volumes/2TB/MAS/openclaw-core/ORBIT
source /Users/visen24/anaconda3/etc/profile.d/conda.sh
conda env create -f config/environment.yml || true
conda activate Orbit
pip install -e .
orbit demo
```

## Environment and persistence direction

- Default development environment: Conda environment `Orbit`
- Long-term architectural persistence direction: PostgreSQL
- Current default local/bootstrap backend in v0: SQLite
- SQLite in the current scaffold should be treated as acceptable v0 bootstrap persistence, not the intended long-term default

## Project Structure

- `apps/` — runnable application entrypoints and compatibility launch surfaces
- `config/` — environment and configuration artifacts
- `src/orbit/runtime/` — core runtime contracts, coordinator, event vocabulary, plans, normalization
  - `providers/` — provider-specific execution backends (`openai_platform`, `openai_codex`, `ssh_vllm`)
  - `auth/` — OAuth/auth-material helpers and local auth stores
  - `transports/` — HTTP, SSE, and SSH tunnel helpers
- `src/orbit/store/` — persistence boundary plus SQLite/PostgreSQL implementations
- `src/orbit/notebook/` — DataFrame projections and notebook workbench/provider demo helpers
- `src/orbit/tools/` — tool abstractions and registry
- `notebooks/` — notebook-first demonstrations of runtime capabilities
- `docs/` — grouped repository-facing documentation
  - `architecture/` — architecture notes
  - `setup/` — environment/setup docs
  - `persistence/` — persistence direction notes
- `notebooks/runtime/` — runtime and approval-path demos
- `notebooks/workbench/` — operator/workbench inspection demos
- `notebooks/providers/` — provider comparison and live-backend demos
- `notes/scaffold/` — local scaffold/demo support files

See also: `docs/project-structure.md`.
