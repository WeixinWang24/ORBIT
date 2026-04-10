# ORBIT

ORBIT is a Python-first, governance-oriented personal agent workbench.

## Current scope

This repository currently contains a Phase 0/1 workbench for:
- typed core domain objects
- an active SessionManager-centered runtime mainline
- structured runtime events plus transcript/session persistence
- temporary bootstrap persistence with PostgreSQL as the architectural direction
- governed native tool calling
- a first Python-first MCP filesystem re-entry slice
- notebook-friendly and local web-inspector observation surfaces

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

Project-local machine configuration can be persisted in `.env.local` at the repo root. ORBIT now loads this file as part of CLI/runtime startup, so values such as `ORBIT_OBSIDIAN_VAULT_ROOT` do not need to be re-exported manually every run. The existing helper `./scripts/bootstrap.sh obsidian` is part of this same persistence path and writes the vault setting into `.env.local` for you.

```bash
cd /Volumes/2TB/MAS/openclaw-core/ORBIT
source /Users/visen24/anaconda3/etc/profile.d/conda.sh
conda env create -f config/environment.yml || true
conda activate Orbit
python -m pip install -e .
orbit
```

## Current terminal entrypoints

The runtime-first PTY CLI/workbench is now the primary terminal surface for ORBIT.

Primary commands:

```bash
orbit
orbit-session
orbit-runtime-workbench
```

All three currently launch the same runtime-first terminal UI:
- `orbit.interfaces.pty_runtime_cli:browse_runtime_cli`

Recommended usage:
- use `orbit` as the default human-facing terminal entrypoint
- use `orbit-session` only as a compatibility alias during transition
- use `orbit-runtime-workbench` when you want the entrypoint name to be explicit in scripts/docs

Direct Python module entry:

```bash
python -m orbit.interfaces.pty_runtime_cli
```

Current command surface inside the new terminal UI includes session/runtime control such as:
- `/sessions`
- `/attach <session_id>`
- `/new`
- `/detach`
- `/show`
- `/state`
- `/events`
- `/approvals`
- `/pending`
- `/approve [note]`
- `/reject [note]`
- `/clear`
- `/clear-all`
- `/status`
- `/help`

## Build creation / activation commands

ORBIT currently has two related command-line layers for build work:

1. **Runtime/self-change build-management slice**
   - this is the new `SelfChangePlan` / `BuildRecord` lifecycle in the runtime
   - current first slice is primarily code/API-driven and persists through `session.metadata`, `ContextArtifact`, and `ExecutionEvent`
   - it is not yet a standalone human-facing CLI command family

2. **Repo/runtime build activation commands**
   - this is the existing command surface for creating/loading the repo/runtime build that the workbench launches against

Current repo/runtime build commands:

```bash
# create a new candidate build record
python apps/orbit_build_cli.py create-candidate --mode dev
python apps/orbit_build_cli.py create-candidate --mode evo

# create a materialized candidate build
python apps/orbit_build_cli.py materialize-candidate --mode dev
python apps/orbit_build_cli.py materialize-candidate --mode evo

# promote current candidate build to active
python apps/orbit_build_cli.py promote-candidate

# print the launch command for the active build
python apps/orbit_build_cli.py print-active-launch

# compatibility launcher helper
python apps/orbit_print_active_launch.py

# directly launch the current active build
python apps/orbit_launch_active.py
```

Current runtime truth for `materialize-candidate`:
- the current repo remains the development target
- candidate materialization now builds a wheel from the repo
- each build gets a per-build `runtime_root` and generated launcher
- active launch binds to the current Conda Python while loading ORBIT code from the build runtime root
- the active runtime is no longer expected to import ORBIT code from the live repo

This is a first-slice shared-environment model:
- code artifact isolation per build
- shared Conda dependency environment
- `promote-candidate` still only performs activation-pointer switching

Recommended operational sequence:

```bash
# 0) enter the ORBIT repo with the dedicated Conda env
source /Users/visen24/anaconda3/etc/profile.d/conda.sh
conda activate Orbit
cd /Volumes/2TB/MAS/openclaw-core/ORBIT

# optional but recommended: persist Obsidian vault config once in .env.local
# either use the interactive bootstrap helper:
#   ./scripts/bootstrap.sh obsidian
# or create/edit .env.local manually:
#   cp .env.local.example .env.local
#   export ORBIT_OBSIDIAN_VAULT_ROOT="/absolute/path/to/your/obsidian/vault"

# 1) create and materialize a candidate build for evo mode
python apps/orbit_build_cli.py materialize-candidate --mode evo

# 2) inspect current build pointers if desired
python - <<'PY'
from orbit.runtime.governance.build_state_store import BuildStateStore
store = BuildStateStore()
pointer = store.load_activation_pointer()
print(pointer.model_dump_json(indent=2))
PY

# 3) promote that candidate to active
python apps/orbit_build_cli.py promote-candidate

# 4) inspect what command the active build will launch with
python apps/orbit_build_cli.py print-active-launch

# 5) launch the current active build
python apps/orbit_launch_active.py
```

One-line full flow:

```bash
source /Users/visen24/anaconda3/etc/profile.d/conda.sh && \
conda activate Orbit && \
cd /Volumes/2TB/MAS/openclaw-core/ORBIT && \
python apps/orbit_build_cli.py materialize-candidate --mode evo && \
python apps/orbit_build_cli.py promote-candidate && \
python apps/orbit_build_cli.py print-active-launch && \
python apps/orbit_launch_active.py
```

Launch latest candidate without promoting:

```bash
source /Users/visen24/anaconda3/etc/profile.d/conda.sh
conda activate Orbit
cd /Volumes/2TB/MAS/openclaw-core/ORBIT

python - <<'PY'
from orbit.runtime.governance.build_state_store import BuildStateStore
import subprocess

store = BuildStateStore()
pointer = store.load_activation_pointer()
build_id = pointer.candidate_build_id
if not build_id:
    raise SystemExit("no candidate build configured")
cmd = store.stable_launch_command_for_build(build_id)
print("Launching:", " ".join(cmd))
raise SystemExit(subprocess.call(cmd))
PY
```

Notes:
- these commands manage the repo/runtime build pointers and materialized build launcher flow
- state is managed through `src/orbit/runtime/governance/build_state_store.py`
- build provenance now includes source identity / dirty-state tracking to support later active-baseline understanding
- they are distinct from the new self-change/build-management runtime records
- in the current first slice, self-change/build-management is governance/runtime truth, while build CLI commands remain the launcher/runtime-build control surface
- Obsidian vault persistence path is now unified: `./scripts/bootstrap.sh obsidian` writes `ORBIT_OBSIDIAN_VAULT_ROOT` into `.env.local`, and runtime startup loads `.env.local` automatically
- if `ORBIT_OBSIDIAN_VAULT_ROOT` is absent in both the live environment and `.env.local`, the runtime now silently skips Obsidian MCP activation instead of blocking startup

## Environment and persistence direction

- Default development environment: Conda environment `Orbit`
- Long-term architectural persistence direction: PostgreSQL
- Current default local/bootstrap backend in v0: SQLite
- SQLite in the current scaffold should be treated as acceptable v0 bootstrap persistence, not the intended long-term default

## Project Structure

- `apps/` — runnable application entrypoints and compatibility launch surfaces
- `config/` — environment and configuration artifacts
- `src/orbit/runtime/` — active runtime contracts, session loop, providers, governance, MCP bootstrap/integration
  - `core/` — SessionManager mainline and runtime contracts/events
  - `providers/` — provider-specific execution backends (`openai_platform`, `openai_codex`, `ssh_vllm`)
  - `mcp/` — MCP client/bootstrap/governance/registry-loading integration
  - `auth/` — OAuth/auth-material helpers and local auth stores
  - `transports/` — HTTP, SSE, and SSH tunnel helpers
- `src/mcp_servers/` — cross-runtime MCP server assets
  - `system/core/filesystem/` — Python-first local filesystem MCP capability family (`read_file`, `list_directory`, `list_directory_with_sizes`, `get_file_info`, `directory_tree`, `search_files`)
- `src/orbit/store/` — persistence boundary plus SQLite/PostgreSQL implementations
- `src/orbit/notebook/` — DataFrame projections and notebook workbench/provider demo helpers
- `src/orbit/tools/` — governed native tool abstractions plus MCP wrappers/registry
- `src/orbit/web_inspector.py` — local inspector for transcript, payload, context, events, and tool calls
- `notebooks/` — notebook-first demonstrations of runtime capabilities
- `docs/` — grouped repository-facing documentation
  - `architecture/` — architecture notes
  - `setup/` — environment/setup docs
  - `persistence/` — persistence direction notes
- `notebooks/runtime/` — runtime and approval-path demos
- `notebooks/workbench/` — operator/workbench inspection demos
- `notebooks/providers/` — provider comparison and live-backend demos
- `notes/scaffold/` — local scaffold/demo support files

See also:
- `docs/project-structure.md`
- `docs/architecture/overview.md`
- `docs/session-manager-mvp-loop-contract.md`
- `docs/filesystem-runtime-quality-roadmap.md`
- `docs/mcp-adapter-layering-design.md`
