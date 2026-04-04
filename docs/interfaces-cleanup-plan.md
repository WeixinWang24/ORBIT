# ORBIT Interfaces Cleanup Plan

## Goal

Reduce `src/orbit/interfaces/` from a mixed experimental area into a clearer structure centered on the now-preferred raw PTY runtime CLI.

## File classification

### Keep as active mainline
- `contracts.py`
- `mock_adapter.py`
- `chat_mock_adapter.py`
- `termio.py`
- `input.py`
- `pty_debug.py`
- `pty_runtime_router.py`
- `pty_runtime_cli.py`

### Keep as reference authority
- `pty_workbench.py`

### Keep as entrypoints
- package scripts: `orbit`, `orbit-session`, `orbit-runtime-workbench`

### Removed legacy wrappers
- `apps/orbit_interface_cli.py`
- `apps/orbit_workbench.py`

### Removed fallback / mock / transitional files
- `ptk_workbench.py`
- `raw_runtime_workbench.py`
- `cli_mock.py`
- `web_mock.py`
- `style_vio.py`

## Cleanup principles

1. Do not disturb the preferred raw PTY reference shell (`pty_workbench.py`).
2. Do not disturb the active runtime-first raw CLI mainline (`pty_runtime_cli.py`).
3. Remove or archive fallback/scaffold files only after confirming no active entrypoint depends on them.
4. Keep `input.py` as the primary home for low-level control-sequence handling.
5. Preserve mock adapter contracts while real runtime integration is still pending.

## Immediate next cleanup actions

1. Clarify package/module top-level description (`__init__.py`) so new work defaults to the raw PTY mainline.
2. Remove obviously inactive fallback implementations from the active mental surface.
3. Update documentation / KB to reflect the cleaned structure.
4. Keep only one active runtime CLI path and one reference shell path.
5. Remove legacy wrappers once active entrypoints and docs are aligned.

## Legacy entrypoint disposition

### Active entrypoints
- `orbit` / `orbit-session` / `orbit-runtime-workbench` → active runtime-first entry surface

### Removed legacy wrappers
- `apps/orbit_interface_cli.py`
- `apps/orbit_workbench.py`
- `apps/orbit_runtime_workbench.py`
- `apps/orbit_workbench_raw.py`

These wrapper-style entrypoints have now been removed from the active repo surface after package/docs alignment, to keep the active code surface clean.
