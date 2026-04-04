# ORBIT Interface Isolated Development Plan

## Purpose

This note records the current interface-development posture for ORBIT after the terminal UI direction converged on the raw PTY runtime workbench.

The immediate goal is no longer to keep many competing interface shells alive. The goal is to preserve one clear terminal reference surface, one active runtime CLI mainline, and one input subsystem mainline.

## Current terminal interface authority

### Interaction / display authority
- `src/orbit/interfaces/pty_workbench.py`

This file is the authoritative reference for:
- divider-based sectioning
- highlighted/focused selection rows
- color-coded emphasis
- `t` / `Shift+Tab` tab switching
- `Enter` drill-down behavior
- top-fixed header/tab region plus middle work-area composition

### Runtime-first terminal mainline
- `src/orbit/interfaces/pty_runtime_cli.py`
- package scripts: `orbit`, `orbit-session`, `orbit-runtime-workbench`

This is the active raw PTY runtime CLI path for ongoing CLI work.

### Input subsystem mainline
- `src/orbit/interfaces/input.py`

This file now owns the low-level control-sequence assembly direction:
- pending control-sequence reassembly
- stale fragment ageing / forced flush
- bare Escape completion
- broader fragment detection

## Current file roles

### Active mainline files
- `contracts.py`
- `mock_adapter.py`
- `chat_mock_adapter.py`
- `termio.py`
- `input.py`
- `pty_debug.py`
- `pty_runtime_router.py`
- `pty_runtime_cli.py`

### Reference authority file
- `pty_workbench.py`

### Active entrypoints
- package scripts: `orbit`, `orbit-session`, `orbit-runtime-workbench`

## Legacy / cleanup status

The following files are no longer the terminal UX authority and should be treated as legacy, fallback, or cleanup targets rather than active design centers:
- `ptk_workbench.py`
- `raw_runtime_workbench.py`
- `cli_mock.py`
- `web_mock.py`
- `style_vio.py`
- `apps/orbit_interface_cli.py`
- `apps/orbit_workbench.py`

## Current product direction

### Chat page
- default homepage = Agent Runtime Chat
- top message panel + bottom one-line composer
- plain text input goes to runtime chat
- slash commands switch modules

### Non-chat pages
- preserve raw PTY navigation logic
- direction keys / `j k` / `Enter` / `Tab` / `Shift+Tab`
- `c` returns to chat
- `Ctrl+C` exits

## Cleanup principle

Do not re-introduce multiple competing CLI mainlines.

If new runtime-first terminal functionality is added:
1. terminal interaction/display reference comes from `pty_workbench.py`
2. runtime product behavior lands in `pty_runtime_cli.py`
3. low-level control-sequence hygiene lands in `input.py`

## Next-step rule

When uncertain where a change belongs:
- visual/layout/navigation pattern → `pty_workbench.py` reference
- runtime CLI page/state/router behavior → `pty_runtime_cli.py`
- ESC/CSI/mouse/focus/input assembly → `input.py`
