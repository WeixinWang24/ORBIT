# MCP Asset Audit and Coding Agent Roadmap (2026-04-04)

## Purpose

This note captures the current MCP capability inventory in ORBIT and compares it against the operational surface expected from a fuller coding agent runtime.

The goal is not just to list tools.
The goal is to understand:
- what ORBIT already has
- what is already stronger than it first appears
- what capability gaps still remain
- what the next operational-surface priorities should be

---

## Current MCP asset inventory

### 1. Filesystem MCP server

Current canonical tools in the filesystem server:

#### Discovery / Read
- `read_file`
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `glob`
- `search_files`
- `grep`

#### Mutation
- `write_file`
- `replace_in_file`
- `replace_all_in_file`
- `replace_block_in_file`
- `apply_exact_hunk`
- `apply_unified_patch`

### 2. Bash MCP server

Current canonical tool:
- `run_bash`

### 3. Process MCP server

Current canonical tools:
- `start_process`
- `read_process_output`
- `wait_process`
- `terminate_process`

---

## Operational-surface interpretation

### What ORBIT already has

#### A. Filesystem discovery surface already exists

A key audit finding is that ORBIT already has more discovery surface than it first appeared to have.
The filesystem server already provides:
- directory listing
- directory listing with sizes/summary
- file metadata
- bounded directory tree
- bounded text search across files

This means ORBIT does **not** need to reinvent `list_directory` as a new MCP family capability.
The right move is to recognize these as existing discovery assets and normalize them into the coding-agent operational picture.

#### B. Filesystem mutation surface is already strong

ORBIT already has a strong first-slice mutation family with:
- file write
- exact replace
- replace-all
- block replace
- exact hunk apply
- strict single-file unified patch apply

This surface is not only implemented, but integrated into:
- MCP naming
- runtime governance
- approval/grounding semantics
- session/transcript flow

#### C. One-shot shell surface exists

`run_bash` now provides:
- one-shot shell execution
- classification
- approval split
- subprocess env scrub policy
- output metadata
- layered failure semantics

This is a meaningful coding-agent operational surface, even if it remains smaller than Claude Code's shell stack.

#### D. Process lifecycle surface exists

ORBIT now also has a real process-lifecycle slice with:
- persistent process identity
- service-backed lifecycle handling
- MCP exposure
- session/runtime integration

This is especially important because a full coding agent needs more than one-shot shell execution.

---

## Comparison against a fuller coding-agent operational surface

When compared with a more mature coding-agent runtime (for example, Claude Code's combined filesystem/shell/task surfaces), ORBIT still has several meaningful gaps.

### 1. Search / discovery is only partially complete

#### Already present
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `search_files`
- `read_file`

#### Still missing or not yet normalized enough
- a more coding-agent-shaped `grep` surface, or a clear decision that `search_files` should be promoted into that role
- stronger discovery-family documentation/contract clarity across path discovery vs content discovery
- possible later repo-scale runtime-quality work such as ignore-policy refinement or faster large-repo matching substrate

This is still the single most important correction to earlier planning.
The next discovery step was not “build discovery from scratch”.
The first normalization wave has now confirmed the better direction was:
- audit
- normalize
- fill the obvious gap (`glob`)
- make discovery pagination/continuation coherent enough for real coding-agent exploration

### 2. Planning / todo surface has now begun, but remains first-slice only

ORBIT now has a clear first operational surface for:
- todo writing
- todo reading
- lightweight work decomposition and visible progress state

Current limitation:
- todo truth is still session-scoped and lightweight rather than a fuller persistent/shared planning substrate

This means the gap has narrowed materially, but planning is not yet a fully developed runtime layer.

### 3. Web / docs retrieval surface has now begun, but remains first-slice only

ORBIT now has a runtime-native MCP family entry for:
- web fetch
- governed remote text/doc retrieval in a coding-agent context

Current limitation:
- `web_fetch` is still bounded retrieval-only rather than a richer docs/web analysis stack

This means the gap has narrowed materially, but retrieval is not yet a fully developed runtime layer.

### 4. Bash and process families still have depth gaps

Both families now have credible first slices, but they still trail a mature coding agent in areas such as:
- shell security / sandbox sophistication
- process/task UX and output projection polish
- richer task/productivity layer integration

---

## Stage assessment

### What ORBIT already is

ORBIT is no longer merely a conversation loop with a few tools attached.
It now has a real runtime substrate for coding-agent operations, including:
- governed session runtime
- filesystem discovery + mutation
- shell execution
- process lifecycle
- persistence-backed capability continuity
- MCP family extensibility

### What ORBIT is not yet

ORBIT is not yet a fully rounded coding agent operational surface comparable to a mature system like Claude Code.

The main reasons are now more specific:
- discovery/search first wave exists, but still needs runtime-quality and contract polish
- planning/todo surface now exists only as a lightweight first slice
- web/docs retrieval now exists only as a bounded first slice

---

## Recommended roadmap

### Priority 1 — Discovery surface normalization and gap fill

Do not rebuild `list_directory`.
Instead:
1. treat existing filesystem discovery tools as first-class coding-agent discovery assets
2. define a normalized discovery-surface view over:
   - `list_directory`
   - `list_directory_with_sizes`
   - `get_file_info`
   - `directory_tree`
   - `glob`
   - `search_files`
   - `read_file`
3. preserve bounded, continuation-friendly contracts across discovery primitives
4. decide whether `search_files` should:
   - remain as-is
   - be refined
   - or be promoted into a more explicit `grep`-quality search contract

Current state after the first normalization wave:
- canonical `glob` now exists
- `glob` is integrated through filesystem MCP, governance, registry, and SessionManager runtime truth
- `glob` supports `offset` pagination
- `search_files` now also supports `offset` pagination
- current evaluation result is to keep `search_files` as a paginated bounded content-discovery primitive rather than silently promoting it into grep semantics
- that direction has now been acted on: ORBIT now has a distinct canonical `grep` first slice
- current `grep` first slice already supports regex-style search, `output_mode`, `glob`, `type`, context controls, pagination, and multiline mode
- `grep` currently prefers real `rg` when available and falls back to bounded Python behavior otherwise
- canonical `grep` first slice is now validated both at server level and through SessionManager same-turn closure / pagination paths
- the next unresolved discovery question is therefore grep contract/runtime-quality polish rather than grep introduction or glob absence

### Priority 2 — Todo / planning family

Add an explicit work-management surface such as:
- `todo_write`
- `todo_read`

Current first-slice state:
- canonical `todo_write` and `todo_read` now exist
- current todo truth is session-scoped rather than workspace-global
- the first slice intentionally uses lightweight structured todo state rather than a new store schema
- `todo_write` and `todo_read` are now validated at both server level and SessionManager runtime level
- the next planning-surface question is whether todo truth should remain session-scoped or later graduate into a more persistent/shared runtime substrate

### Priority 3 — Web / docs retrieval family

Add a governed remote text/doc retrieval surface such as:
- `web_fetch`

Current first-slice state:
- canonical `web_fetch` now exists
- current `web_fetch` is retrieval-only rather than fetch-plus-model-summarize
- current `web_fetch` accepts `url`, `max_chars`, `format_hint`, and `extract_main_text`
- current `web_fetch` returns bounded normalized content plus basic metadata (`title`, `content_type`, `status`, `final_url`, truncation metadata)
- current implementation uses lightweight stdlib HTTP fetch + HTML text extraction rather than a heavier third-party content stack
- `web_fetch` is now validated at both server level and SessionManager runtime level
- current governance posture treats `web_fetch` as a safe read capability because it performs bounded retrieval without local file mutation or external side effects beyond the fetch itself
- current intended boundary is public/readable http(s) retrieval rather than authenticated browsing or general crawler behavior
- future hardening may still want stricter policy around localhost/private-network targets, redirect policy, and host-level trust distinctions
- the next docs-retrieval question is how far ORBIT should expand from bounded raw retrieval into richer docs/web analysis ergonomics

### Priority 4 — Continue shell/process polish

Continue improving:
- bash sandbox/security maturity
- process projection and UX maturity
- cleanup / transport polish

### Consistency cleanup note

A companion note now tracks capability-family consistency state and next cleanup actions:
- `docs/capability-family-consistency-cleanup-summary-2026-04-04.md`

---

## Practical conclusion

The next operational-surface step for ORBIT was not “new discovery server from zero”.
The first normalization wave has now validated the better path:
- **filesystem discovery asset normalization**
- plus an explicit **`glob`** addition
- plus pagination-aware continuation for discovery/content-search primitives

That path has now materially improved ORBIT's coding-agent discovery surface.
The next unresolved question is no longer whether ORBIT has discovery primitives.
The next unresolved discovery/search question is how far ORBIT should continue polishing contract consistency and runtime quality across `search_files`, `glob`, and canonical `grep`.
