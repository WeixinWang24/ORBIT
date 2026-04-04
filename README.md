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
