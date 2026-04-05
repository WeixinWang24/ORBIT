# Browser First Slice

## Status

Implemented and locally validated.

This document describes ORBIT's browser-backed verification and light-interaction first slice.
It is intentionally bounded and should not be mistaken for a full browser automation platform.

## Goal

Provide a bounded Web UI truth surface for ORBIT so an agent can:
- open a page
- inspect a bounded structured snapshot of visible UI state
- click and type against snapshot-local element ids
- inspect recent console output
- capture a screenshot artifact

## Current canonical tools

- `browser_open`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_console`
- `browser_screenshot`

## Current implementation posture

This first slice has now entered a migration-first-pass posture toward MCP hosting.
An MCP-hosted browser family now exists and can be mounted. The original per-call stdio MCP client lifecycle was not sufficient for browser continuity, but ORBIT now also has a browser-scoped persistent MCP client path that preserves continuity when browser MCP is explicitly enabled as an experimental path.

Because of that, the current truth is now more specific:
- native browser remains the default validated path
- browser MCP continuity now works in the explicit experimental path (`enable_mcp_browser=True`)
- browser MCP is therefore no longer merely a registration/mounting surface, but it is not yet the default replacement path

The runtime shape remains:
- one browser manager per active browser tool host
- one active browser/context/page
- Playwright-managed Chromium as the browser substrate
- bounded snapshot-local interaction semantics

## What this first slice is for

Use it when the task needs:
- browser-backed page truth
- structured UI inspection
- lightweight click/type interaction against the current page
- recent console inspection for local UI debugging
- screenshot evidence for local Web UI development/verification

## What this first slice is not

This slice does not yet provide:
- multi-tab orchestration
- auth/session profile management
- arbitrary JavaScript evaluation
- network tracing
- a full browser test runner
- stable cross-snapshot element identities beyond the current snapshot-local id model

## Snapshot posture

`browser_snapshot` remains the core reasoning surface in this slice.
It returns a bounded structured element list rather than a full raw DOM dump.
Current element projection focuses on common visible UI primitives such as:
- headings
- links
- buttons
- inputs
- textareas
- selects
- role-bearing elements
- explicitly observed state nodes marked with `data-orbit-observe`

Snapshot element ids are currently snapshot-local.
That means interaction tools (`browser_click`, `browser_type`) should be driven from the latest snapshot rather than assuming ids remain stable across arbitrary page changes.

## Interaction posture

`browser_click` and `browser_type` are now part of the same bounded first slice.
They currently target elements through snapshot-local ids projected by `browser_snapshot`.
This keeps the interaction model simple and agent-usable without introducing a full selector DSL.

`browser_console` exposes a bounded recent-message buffer for basic UI debugging.
It is intentionally modest and should not be mistaken for a full browser event or network inspection surface.

## Screenshot posture

`browser_screenshot` writes a PNG artifact under the workspace-local browser artifact directory.
This is meant to provide evidence and visual confirmation rather than a diffing system.

## Validation status

This slice has been locally validated against a deterministic HTML fixture page using:
- `browser_open`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_console`
- `browser_screenshot`

Migration-first-pass validation confirmed that the browser family can register through the MCP path as `McpToolWrapper` instances with `server_name=browser`, so the shared browser surface is no longer native-only.

That validation initially exposed an architectural limit in the per-call stdio MCP client lifecycle: `browser_open` followed by `browser_snapshot` could lose continuity and fall back to a fresh `about:blank` page state.

A browser-scoped persistent MCP client implementation was then added behind an explicit experimental path, and continuity validation now passes there:
- `browser_open` → `browser_snapshot` preserves the opened page
- `browser_click` → `browser_snapshot` preserves changed UI state
- `browser_type` → `browser_console` / `browser_snapshot` preserves continued interaction state

So the current truth is:
- plain per-call MCP browser hosting is insufficient
- browser-scoped persistent MCP hosting is now working in the explicit experimental path
- default browser truth path remains native until the persistent MCP route is promoted

## Near-term next slice

If ORBIT continues this family, the most natural next additions are now more advanced interaction and observation capabilities beyond the current first slice, for example:
- richer navigation-awareness after click actions
- better cross-snapshot targeting/disambiguation
- stronger console/error classification

Those should remain bounded follow-ups rather than justification to retroactively overstate the current slice.
