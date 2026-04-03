# Filesystem Runtime Quality Roadmap

## Purpose
This note defines the next design layer for ORBIT’s Python-first filesystem capability family.

The current family is no longer a single read helper. ORBIT now has:
- `read_file`
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`

Because the capability family has grown, the next improvement should focus less on adding more tool names and more on strengthening runtime-quality semantics:
- freshness
- deduplication
- partial-view semantics
- bounded output policy
- future write/edit grounding rules

This note is a roadmap/design anchor, not a claim that all items below are already implemented.

---

## Current state

### What is already true
- filesystem MCP tools use workspace-relative canonical paths
- path escape is governed and denied consistently
- results are structured-first and inspectable
- transcript/tool invocation/event/inspector surfaces already agree on runtime truth for the implemented slices
- native tools and MCP tools already share a common governance direction

### What is not yet formalized
- read-state cache semantics
- explicit freshness-aware shortcut result kinds
- the boundary between full read truth and partial/derived view truth
- byte-vs-token output policy as a first-class capability layer
- future write/edit gating rules based on read quality

---

## Design goals

1. Preserve transcript-canonical runtime truth.
2. Keep all runtime-affecting shortcuts explicit and inspectable.
3. Preserve workspace-relative canonical path discipline.
4. Make future write/edit safety depend on grounding quality, not just path familiarity.
5. Keep filesystem capability outputs structured-first.
6. Keep future optimization layers compatible with inspector/tool-call/persistence surfaces.

---

## Roadmap topics

### 1. Read-state cache
Potential future concept:
- a session-scoped filesystem read-state cache
- normalized workspace-relative keys
- range-aware identity (`path + offset + limit` for read-like tools that support ranges)
- freshness timestamp
- explicit `is_partial_view`
- explicit read-origin vs write-origin distinction

Open questions:
- should this cache live in session metadata, a runtime-only structure, or a persisted store layer?
- which filesystem tools should update it?
- should non-read tools (for example future write/edit tools) update freshness markers differently from read tools?

Current recommendation:
- do not implement immediately
- first define the cache shape and lifecycle explicitly

---

### 2. Explicit `unchanged` result kind
Potential future concept:
- repeated identical `read_file` requests against unchanged file content may return a structured `unchanged` result instead of replaying the full content

Possible shape:
```json
{
  "path": "notes/example.txt",
  "status": "unchanged",
  "offset": 0,
  "limit": 200
}
```

Rules that should hold before any future implementation:
- never make this an invisible optimization
- only allow it when ORBIT can prove the earlier read was a trustworthy full/appropriate view for the current request
- transcript/tool invocations/inspector should show this as a first-class result kind

---

### 3. Partial-view semantics
ORBIT should eventually formalize the difference between:
- canonical full read
- partial/truncated view
- transformed/derived/injected view
- future freshness shortcut results

Why this matters:
- partial read truth should not automatically qualify as write/edit grounding
- context compression and repeated-read optimization depend on this distinction

Future likely field:
- `is_partial_view: true|false`

---

### 4. Bounded output policy
Filesystem capability quality should eventually distinguish between at least two resource dimensions:

#### A. IO/storage-side bounds
Examples:
- max bytes to read
- max entries to list
- max nodes in a directory tree
- max recursion depth

#### B. model/context-side bounds
Examples:
- output token budgets
- transcript preview size
- inspector summary size

Future direction:
- some tools may also benefit from prompt-facing hints encouraging more targeted reads when outputs are likely to be large

Current recommendation:
- continue using hard implementation limits now
- later promote these into a more explicit capability policy layer

---

### 5. Read grounding quality and future write/edit safety
If ORBIT later re-enters write/edit filesystem tools through MCP or richer native tools, write safety should not depend only on path identity.

Future distinction should likely include:
- no prior read grounding
- prior read grounding but partial/truncated/derived view
- trustworthy full read grounding
- previously-read content that is now stale on disk

Design principle:
- permission allow is not the same thing as semantic readiness to mutate a file
- write/edit safety should depend on both permission/governance and grounding quality

---

### 6. Tool metadata for filesystem orchestration
As the filesystem family grows, ORBIT should likely formalize some tool-level metadata rather than relying entirely on tool-name heuristics.

Future candidates:
- `is_read_only`
- `is_concurrency_safe`
- `capability_family = filesystem`
- maybe a grounding category for tools whose output may later support write safety

This would support later work on:
- concurrency partitioning
- richer governance
- more explicit capability-family reasoning

---

## Recommended implementation order

### Phase B1 — design clarification only
- define read-state cache shape
- define partial-view semantics
- define a candidate `unchanged` result kind
- define which current tools should or should not participate in future grounding state

Current implementation progress:
- ORBIT now records a minimal `filesystem_read_state` metadata entry for successful `read_file` executions
- the current shape records `source_tool`, `timestamp_epoch`, `is_partial_view`, `grounding_kind`, `path_kind`, and `range`
- truncated `read_file` results now explicitly record `is_partial_view = true` and `grounding_kind = partial_read`
- current grounding participation is intentionally narrow: only `read_file` updates grounding state; `list_directory`, `list_directory_with_sizes`, `get_file_info`, `directory_tree`, and `search_files` do not yet participate
- this is currently recording-only: it does not yet change visible `read_file` behavior or future governance decisions

### Phase B2 — first implementation slice
- introduce read-state cache for `read_file` only
- do not yet optimize output away silently
- optionally record state without changing visible runtime behavior

### Phase B3 — explicit freshness shortcut
- add `unchanged` result kind for strictly safe repeated `read_file` cases
- ensure transcript/tool-call/inspector visibility stays intact

Current implementation progress:
- ORBIT now supports a first explicit `filesystem_unchanged` result for repeated same-path `read_file` requests within a session
- the current trigger is intentionally strict: only a prior `full_read` grounding entry for the same path may produce `status = unchanged`
- the current freshness basis is lightweight but explicit: unchanged requires matching `observed_modified_at_epoch` and `observed_size_bytes` from the prior full read
- file changes now correctly force fallback to a real read instead of producing `filesystem_unchanged`
- prior `partial_read` grounding does not qualify
- the shortcut remains explicit and inspectable through normal tool-result surfaces; it is not a silent optimization

### Phase B4 — write/edit coupling
- when write/edit paths expand later, consume grounding-quality state explicitly instead of assuming any prior path touch is enough

Current implementation progress:
- ORBIT now exposes an explicit per-path grounding-readiness classification helper for the current session state
- current statuses are: `none`, `partial_only`, `full_read_fresh`, and `full_read_stale`
- ORBIT also now exposes a first mutation-facing readiness helper that maps grounding state into write eligibility/reason for a path
- current write-readiness reasons are: `no_prior_grounding`, `partial_read_grounding_insufficient`, `stale_full_read_grounding`, and `full_read_fresh_grounding_available`
- ORBIT now uses this helper to gate `native__write_file` at execution time: approval alone is no longer enough when grounding is missing or stale
- ORBIT also now applies the same gate to the first minimal edit-family path, `native__replace_in_file`
- ORBIT also now applies the same gate to the first multi-hit edit-family path, `native__replace_all_in_file`
- grounded mutation results are also beginning to converge on a shared minimal contract (`mutation_kind`, path, optional replacement counts, exact-match counters, and layered failure markers)
- ORBIT now also has its first exact block-level grounded mutation path: `native__replace_block_in_file`
- this remains intentionally narrow: richer fuzzy/diff-hunk mutation families are still future work

---

## What this roadmap is intentionally not doing yet
- it does not introduce write/edit MCP tools now
- it does not add hidden read dedup shortcuts now
- it does not replace transcript truth with cache truth
- it does not copy the external absolute-path model used in other runtimes

---

## External reference alignment
This roadmap is informed by:
- Claude Code filesystem tool/runtime reference analysis
- absorbed lessons on tool orchestration and hook invariants
- ORBIT’s existing Python-first filesystem MCP capability family and current SessionManager mainline

The intended ORBIT stance remains:
- absorb proven external ideas
- preserve ORBIT-native governance, runtime truth, and structured observation model
