# ORBIT Interface Isolated Development Plan

## Purpose

This note defines the isolated development posture for the next ORBIT interface work phase.

It assumes:
- another agent is actively modifying MCP and tools capability surface
- that work may also touch current runtime and web inspector paths
- the safest acceleration path is to let interface work proceed in parallel without direct runtime coupling

## Development stance

Current interface work should be split into two isolated modules:
- **mock-driven Web workbench shell**
- **mock-driven CLI workbench shell**

Both should depend on a shared adapter contract layer rather than on direct SessionManager wiring.

## New module surfaces

### Source package
- `src/orbit/interfaces/`
  - `contracts.py` — adapter-facing view-model contracts
  - `mock_adapter.py` — deterministic mock data provider
  - `web_mock.py` — isolated browser-facing workbench shell
  - `cli_mock.py` — isolated CLI workbench shell

### App wrappers
- `apps/orbit_interface_cli.py`

## Contract shape

The interface adapter currently assumes these read-oriented operations:
- `list_sessions()`
- `get_session(session_id)`
- `list_messages(session_id)`
- `list_events(session_id)`
- `list_artifacts(session_id)`
- `list_tool_calls(session_id)`
- `list_open_approvals()`

This keeps first-wave UI work focused on inspection and operator navigation.

## Why inspection-first

Inspection-first isolated work is the least conflict-prone path because it:
- avoids mutating runtime semantics for provisional UI needs
- avoids depending on unstable action/write paths during kernel churn
- still lets us stabilize layout, view models, tabs, navigation, and output grammar

## Planned next integration step

Once runtime/MCP/tools work is stable again, add a real adapter implementation that maps:
- `SessionManager`
- store session/message/event/artifact/tool-call records
- approval queue access

into the same contracts already used by the mock interface layer.

At that point, Web UI and CLI shells should swap adapters rather than redesign structure.
