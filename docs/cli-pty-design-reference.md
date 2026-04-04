# ORBIT CLI PTY Design Reference

## Purpose

This note records the current PTY design conclusions for ORBIT after direct user testing of multiple terminal UI variants.

Earlier references to mock/PTK-first directions are now historical. The present reference point is the raw PTY route.

## Current accepted terminal direction

### Preferred UX authority
- `src/orbit/interfaces/pty_workbench.py`

Why this is preferred:
- stronger terminal-native feel
- faster / more direct interaction
- better perceived stability and responsiveness
- preferred display composition and navigation semantics

### Active runtime CLI mainline
- `src/orbit/interfaces/pty_runtime_cli.py`
- package entrypoints: `orbit`, `orbit-session`, `orbit-runtime-workbench`

This is the active runtime-first raw PTY CLI path.

### Input authority
- `src/orbit/interfaces/input.py`

This is now the preferred home for:
- ESC-prefixed control-sequence assembly
- broken fragment reassembly
- stale fragment ageing/flush behavior
- low-level input hygiene for the raw PTY route

## Preserved raw PTY interaction anchors

The following qualities from `pty_workbench.py` must remain authoritative:
- divider-based page separation
- highlighted/focused row selection
- color-coded status/content emphasis
- `t` / `Shift+Tab` tab switching
- `Enter`-driven page entry/drill-down
- fixed header/tab region + central work-area layout

## Runtime-first behavioral overlay

The runtime CLI mainline layers product behavior on top of that raw PTY shell language:
- default homepage = Agent Runtime Chat
- bottom one-line composer
- slash commands route to non-chat modules
- non-chat pages remain navigation-first rather than composer-first

## Current key rules

### Chat page
- plain text → runtime chat
- slash text → module routing
- `Up/Down/PageUp/PageDown/Home/End` → history/content scrolling
- `Enter` → submit
- `Ctrl+C` → exit

### Non-chat pages
- `↑↓` / `j k` → navigation or page scrolling
- `Enter` → select / enter where relevant
- `t` / `Shift+Tab` → switch inspect tabs where relevant
- `c` → return to chat
- `Ctrl+C` → exit

## Engineering direction

### Keep
- `termio.py`
- `input.py`
- `pty_debug.py`
- `pty_runtime_router.py`
- `pty_runtime_cli.py`
- `pty_workbench.py` (reference authority)

### Demote / cleanup
- prompt_toolkit fallback path
- older mock CLI / mock web workbench scaffolds
- transitional raw runtime experiments that are no longer the chosen mainline

## Short conclusion

The current ORBIT PTY direction is no longer “evaluate many shells.”
It is now:
- raw PTY as preferred terminal UX
- `pty_workbench.py` as visual/interaction authority
- `pty_runtime_cli.py` as runtime-first CLI mainline
- `input.py` as the growing low-level input subsystem
