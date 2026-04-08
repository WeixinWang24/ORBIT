# ORBIT Source Layout

## Current high-level structure

- `apps/`
  - runnable entrypoint wrappers such as `apps/orbit_cli.py`
- `config/`
  - environment/configuration artifacts such as `config/environment.yml`
- `src/orbit/runtime/`
  - `core/` — core runtime contracts, coordinator, and events
  - `execution/` — execution-layer backends, normalization, contracts, and engines
  - `providers/` — provider/back-end specific execution routes
  - `auth/` — auth and credential helpers
  - `transports/` — HTTP / SSE / SSH tunnel transport helpers
- `src/orbit/notebook/`
  - `display/` — notebook-facing projection and table helpers
  - `providers/` — provider-specific notebook helpers
  - `workbench/` — notebook workbench helpers
- `docs/architecture/`
  - architecture notes
- `docs/setup/`
  - setup documentation
- `docs/persistence/`
  - persistence notes
- `notebooks/runtime/`
  - runtime and approval demos
- `notebooks/workbench/`
  - workbench/operator demos
- `notebooks/providers/`
  - provider-route demos
- `notes/scaffold/`
  - scaffold support files
- `src/orbit/store/`
  - persistence interfaces and implementations
- `src/orbit/tools/`
  - tool registry and tool implementations
- `src/mcp_servers/`
  - `system/core/filesystem/` — workspace-scoped filesystem MCP server assets
  - `system/core/git/` — workspace-scoped read-only git MCP server assets
  - `system/core/bash/` — workspace-scoped bash MCP server assets
  - `system/core/process/` — workspace-scoped managed-process MCP server assets
- `src/mcp_servers/`
  - `system/core/filesystem/` — workspace-scoped filesystem MCP server assets
  - `system/core/git/` — workspace-scoped read-only git MCP server assets
  - `system/core/bash/` — workspace-scoped bash MCP server assets
  - `system/core/process/` — workspace-scoped managed-process MCP server assets
  - `apps/obsidian/` — Obsidian MCP server app-scoped entrypoint and vault-introspection/read/search assets for knowledge-management workflows

## Current posture

The older flat provider/auth/transport runtime files have been removed.
The grouped layout is the real source layout, not just a conceptual overlay.
At the repository level, root-directory clutter should also be reduced by grouping runnable entrypoints under `apps/` and configuration artifacts under `config/` whenever doing so improves discoverability.
