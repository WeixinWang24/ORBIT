# PTY Runtime CLI Migration / Carryover Checklist (2026-04-04)

## Purpose

This note captures which CLI-facing lessons from the recent MCP/governed-tools debugging pass should now move onto the **active runtime-first PTY CLI mainline**.

Current active terminal mainline:
- `src/orbit/interfaces/pty_runtime_cli.py`
- `src/orbit/interfaces/runtime_cli_handlers.py`
- `src/orbit/interfaces/runtime_cli_render.py`
- `src/orbit/interfaces/runtime_cli_state.py`

This note exists because some debugging and UX experiments happened against older CLI assumptions while the repo has already declared the runtime-first PTY CLI as the primary terminal surface.

The goal is therefore not to preserve the old entrypoint behavior as-is.
The goal is to preserve the **validated product needs** and remap them onto the active CLI architecture.

---

## 1. Confirmed product needs discovered during MCP CLI testing

### A. Tool visibility must be inspectable
During CLI/provider debugging, it became clear that operator-visible tool registration state is critical.

What was learned:
- it is not enough for tools to exist in the SessionManager registry
- the operator needs a fast way to confirm which tools are visible at the current runtime surface
- in some failure cases, the registry and the provider payload can diverge

Carryover need for PTY CLI:
- add a tool-visibility surface to the active CLI
- likely destinations:
  - status pane
  - inspect pane
  - dedicated tools subview

Recommended first slice:
- show registered tool count
- show current tool names
- optionally show provider-facing tool names if available

---

### B. Provider payload visibility is operationally important
The CLI debugging pass showed that a major failure mode was:
- tools existed in registry
- but provider payload did not include them

Carryover need for PTY CLI:
- expose last provider payload metadata in inspect/status views
- especially the tool list actually sent to the provider

Recommended first slice:
- inspect panel should be able to show:
  - last provider payload tool names
  - tool count sent to provider
  - whether tool_choice was enabled

---

### C. Approval flow must be treated as a first-class interaction state
The debugging pass confirmed that approval is not an edge case.
It is part of the normal product experience.

Validated needs:
- pending approval must be visible without digging
- approval detail must include tool name and input payload summary
- the operator needs direct approve/reject actions
- approval resolution must distinguish between:
  - pending cleared
  - pending cleared but a new pending approval was opened
  - pending remained unexpectedly (bug/diagnostic case)

Carryover need for PTY CLI:
- approval action handling belongs in the active approvals mode, not in removed legacy CLI paths

Recommended first slice:
- approvals pane shows selected approval detail
- approvals pane allows approve/reject action keys or command routing
- after approval resolution, surface whether the old approval cleared and whether a new one opened

---

### D. Approval robustness needs explicit diagnostics
A debugging pain point was ambiguity between:
- approval not being resolved
- approval being resolved but resumed run opening a new approval
- approval resolution succeeding but UI not reflecting it clearly

Carryover need for PTY CLI:
- approval resolution UI should compare pre/post pending approval state explicitly

Recommended first slice:
- show previous approval id
- show current approval id (if any)
- explicitly render one of:
  - approval resolved, no pending remains
  - approval resolved, new pending opened
  - approval may not have cleared correctly

---

### E. Mutating shell command results need better interpretation support
The debugging pass validated that shell commands like:
- `kill ...`
- `touch ...`
- other silent state-changing commands
can succeed with no stdout/stderr output.

This caused model-side over-cautious answers.

Carryover need for PTY CLI and adapter/transcript surfaces:
- preserve and display structured shell execution summaries
- keep `verification_suggested` visible enough that the operator/model can follow up with a read-only verification step

Recommended first slice:
- inspect/tool-call surfaces should display:
  - `execution_summary`
  - `verification_suggested`

---

### F. Read-only shell diagnostics should avoid unnecessary approval friction
The debugging pass also validated that read-only shell command chains such as:
- `command -v lsof && lsof ... || command -v ss && ss ...`
should not be treated like mutating shell commands just because they contain `&&`, `||`, or `|`.

This classification work was fixed at runtime level.

Carryover need for PTY CLI:
- approval views should not assume all bash requests are inherently mutating
- side-effect class and classification details should remain visible in inspect/approval views

---

## 2. What should NOT be carried over literally

### A. Do not revive `cli_session.py` as the mainline
The repo now explicitly documents the active terminal mainline as `pty_runtime_cli.py`.

Therefore:
- do not migrate by restoring old CLI entrypoint assumptions
- do not treat old slash-command handling as the architectural baseline

### B. Do not copy old debug behavior mechanically
Some old debugging helpers were useful, but in the active PTY CLI they should land as:
- status surface
- inspect pane data
- approval pane diagnostics
not necessarily as raw startup printouts

---

## 3. Recommended carryover targets in the active CLI stack

### `runtime_cli_render.py`
Good candidates:
- richer approval detail rendering
- approval outcome status lines
- tool visibility/status summaries
- tool-call execution summary rendering

### `runtime_cli_handlers.py`
Good candidates:
- approval action handling
- approval-specific navigation/actions
- inspect/status shortcuts for provider/tool visibility

### `runtime_cli_state.py`
Good candidates:
- explicit transient state for approval outcome banners
- provider/tool visibility panel selection state if needed

### adapter layer (`runtime_adapter.py` and related adapter protocol surfaces)
Good candidates:
- methods for listing provider-visible tools
- methods for exposing last provider payload summaries
- methods for resolving approvals cleanly from the PTY UI

---

## 4. Recommended migration order

### Priority 1
Bring approval flow fully into the PTY approvals mode:
- approve/reject action support
- clear selected approval detail
- approval outcome diagnostics

### Priority 2
Expose provider/tool visibility in inspect or status views:
- registry tools
- provider-sent tools
- tool counts

### Priority 3
Expose shell/process/tool-call result summaries better:
- `execution_summary`
- `verification_suggested`
- process lifecycle summaries

### Priority 4
Only after the above, consider more ergonomic extras such as:
- recent process id hints
- dedicated tools pane
- more compact provider-payload diffing

---

## 5. Bottom line

The debugging pass against governed MCP tooling produced real product lessons.
Those lessons should now be migrated onto the active PTY runtime CLI mainline, not left attached to removed legacy entrypoints.

The most valuable carryover areas are:
- approval UX
- approval diagnostics
- tool/provider visibility
- better presentation of structured tool results
