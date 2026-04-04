# ORBIT Interface Reference Inspirations

## Purpose

This note records the current visual and interaction inspirations chosen for the isolated ORBIT interface work.

The goal is not to clone another surface exactly, but to borrow stable design language and command-organization ideas while keeping ORBIT's interface implementation isolated from the active runtime/MCP development path.

## Web UI inspiration

### Source
- OpenClaw fork `apps/vio`
- inspected files:
  - `apps/vio/public/index.html`
  - `apps/vio/public/styles.css`
  - `apps/vio/public/app.js`

### Borrowed design language
For the ORBIT mock workbench shell, we should borrow:
- three-column workbench layout
- topbar with brand + status chips
- left sidebar for session/navigation surfaces
- center main work area with tabbed content
- right rail for metadata / operational summary / approvals
- neon-dark Vio palette vocabulary:
  - dark background planes
  - cyan / pink / purple accents
  - rounded cards and chip-based status language

### What not to borrow directly
- Vio runtime-specific module wiring
- current message-runtime bootstrap code
- current app-specific workspace/editor/terminal coupling
- any direct assumptions tied to Vio's runtime event or chat lifecycle

The ORBIT interface layer should only borrow:
- layout grammar
- visual hierarchy
- panel/tabs/chips vocabulary

## CLI inspiration

### Source family
Borrow command-organization ideas from modern coding-agent / operational CLIs, represented here by inspected OpenClaw extension CLI surfaces such as:
- `extensions/voice-call/src/cli.ts`
- `extensions/matrix/src/cli.ts`
- `extensions/openshell/src/cli.ts`

And by user intent specifically referencing Claude Code style.

### Borrowed CLI traits
The ORBIT mock CLI should evolve toward:
- nested command groups instead of one flat command list
- clear command nouns such as:
  - `session`
  - `approval`
  - `tool-call`
  - `workbench`
- readable help text per command
- structured inspection output
- explicit verbs:
  - `list`
  - `show`
  - `inspect`
  - `tail`
  - `status`

### What not to borrow directly
- non-ORBIT provider semantics
- unrelated operational flags
- runtime-specific side effects
- command trees that imply real write/integration actions before ORBIT runtime integration is ready

## Resulting direction

### Web mock shell
- Vio-inspired shell and visual language
- ORBIT-specific data categories and workbench semantics
- mock-adapter driven for now

### CLI mock
- coding-agent-style grouped command tree
- ORBIT-specific nouns and inspectable surfaces
- mock-adapter driven for now

## Short rule

Borrow the **shape** and **interaction grammar**, not the other project's runtime semantics.
