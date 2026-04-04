# ORBIT CLI PTY Design Reference

## Purpose

This note captures CLI / PTY interaction patterns observed in `claude_code_src` and translates them into design guidance for ORBIT's isolated CLI work.

Scope here is **interaction design borrowing**, not code reuse.

## Source scanned

Repository scanned:
- `/Volumes/2TB/MAS/openclaw-core/claude_code_src`

Key files reviewed:
- `src/entrypoints/cli.tsx`
- `src/commands/session/session.tsx`
- `src/commands/help/help.tsx`
- `src/ink/terminal.ts`
- `src/components/QuickOpenDialog.tsx`

## Key observed design patterns

### 1. Fast-path bootstrap before full CLI load
Claude Code's CLI entrypoint strongly separates:
- tiny startup flag handling
- fast-path commands
- only then full CLI/TUI load

Implication for ORBIT:
- PTY CLI should keep a **thin bootstrap path**
- simple commands should avoid loading the whole interactive shell when possible
- interactive PTY mode should be an explicit branch, not the only way to use the CLI

### 2. Clear split between command router and interactive UI
Observed shape:
- command router in entrypoint / command layer
- interactive UI components under terminal UI infrastructure
- command handlers can return JSX/TUI views

Implication for ORBIT:
- keep CLI command parsing separate from PTY rendering
- define command nouns/verbs independently from interactive panes
- allow future commands to render either:
  - plain structured text/json
  - PTY/TUI overlay or panel view

### 3. Overlay-style interaction model
Observed in session/help/quick-open flows:
- focused temporary interaction surfaces
- close/cancel action always available
- modal/overlay interactions are small and single-purpose

Implication for ORBIT:
- PTY UI should not begin as a giant full-screen monolith
- prefer composable interaction surfaces:
  - help overlay
  - session picker
  - approval list
  - quick-open / jump-to-session
  - artifact preview

### 4. Search / picker / preview interaction is first-class
`QuickOpenDialog` is especially relevant:
- query input
- filtered result list
- focused item preview
- keyboard actions for open/insert/cancel

Implication for ORBIT:
A strong PTY workbench pattern would be:
- left = selectable list
- right/bottom = preview/details
- keyboard-driven focus movement
- enter/tab/esc semantics

This is much more useful than a plain REPL once ORBIT has many sessions/artifacts/events.

### 5. Terminal capability awareness matters
`src/ink/terminal.ts` shows Claude Code cares about:
- synchronized output support
- progress reporting support
- terminal capability detection
- cursor behavior edge cases

Implication for ORBIT:
Even in the mock phase, PTY design should assume:
- terminal features vary
- output redraws should be capability-aware later
- fallback plain rendering should remain possible

For ORBIT right now, the practical rule is:
- first design the PTY interaction grammar
- later add capability-aware redraw optimization if we move to a richer TUI runtime

### 6. Keyboard-first navigation is central
Observed interaction principles:
- esc to close/cancel
- tab / shift-tab for alternate actions
- focused item state matters
- terminal UI is built around keyboard affordances

Implication for ORBIT:
PTY design should define keyboard actions explicitly, not implicitly.

Initial ORBIT PTY interaction grammar should likely include:
- `j / k` or arrow keys for navigation
- `enter` for open / inspect
- `tab` for alternate action
- `esc` for cancel / back
- `/` for search/filter
- `?` for help
- `:` for command mode (optional later)

### 7. Command tree and PTY shell are complementary, not competing
Claude-style structure suggests:
- there is a normal command tree
- interactive terminal views sit on top of that
- users can still do direct commands non-interactively

Implication for ORBIT:
We should keep both:
- grouped non-interactive CLI commands
- a future PTY workbench mode

Not either/or.

---

## ORBIT-specific PTY translation

## Recommended PTY shell shape for ORBIT

### Mode 1: structured command mode
Non-interactive and script-friendly:
- `orbit-interface session list`
- `orbit-interface session show <id>`
- `orbit-interface approval list`
- `orbit-interface tool-call list --session <id>`

### Mode 2: PTY workbench mode
Interactive, keyboard-first operator shell:
- `orbit-interface workbench`
- or later `orbit workbench`

This PTY workbench should start small.

## Recommended first PTY screens

### A. Session browser
Layout:
- left: session list
- main: transcript / event summary preview
- right or bottom: metadata / approvals / tool summary

### B. Approval queue
Layout:
- top/left: pending approvals
- preview pane: payload + session context + governance summary
- future action keys reserved for approve/reject once runtime integration exists

### C. Artifact / event inspector
Layout:
- list of artifacts/events
- preview pane with structured content

### D. Help / keybindings overlay
Always available and small.

---

## Recommended PTY interaction rules for ORBIT

### Global
- `q` / `esc` → close current overlay or exit workbench
- `?` → help overlay
- `/` → search/filter mode
- `tab` → cycle panes
- `shift+tab` → reverse cycle panes

### Lists
- `j / down` → next
- `k / up` → previous
- `g` → top
- `G` → bottom
- `enter` → open focused item
- `space` → expand/collapse or toggle preview emphasis

### Future action hooks
Reserved now, wired later when runtime integration is safe:
- `a` → approval action panel
- `r` → refresh/reload adapter data
- `o` → open details view
- `t` → switch transcript / tool / event tabs

---

## Practical implementation advice for ORBIT now

Since current work is still isolated and mock-driven:
- do **not** build a real full Ink-style PTY app yet unless needed
- first evolve the CLI module structure and keyboard interaction spec
- if we add PTY next, prefer a minimal curses/Textual-style prototype or a simple prompt-toolkit/Typer-compatible interactive loop
- keep the PTY shell behind a dedicated command such as `workbench`

## Immediate next coding move

Based on the current repo state, the safest next step is:
1. keep grouped CLI commands intact
2. add a documented `workbench` concept to the CLI mock
3. optionally add a mock keyboard-driven session browser later
4. only after that consider deeper PTY rendering infrastructure

---

## Short conclusion

The main lesson from `claude_code_src` is not “copy this TUI”.
The main lesson is:
- **fast bootstrap**
- **grouped command routing**
- **keyboard-first overlays**
- **search/list/preview workflow**
- **interactive PTY mode layered on top of a usable non-interactive CLI**

That is the right borrowing direction for ORBIT.
