# Capability-Family Consistency Cleanup Summary (2026-04-04)

## Purpose

This note captures the current consistency state of the newly completed ORBIT capability families after the first operational-surface expansion wave.

Covered families:
- discovery / search
- planning / todo
- web / docs retrieval
- filesystem mutation

The goal is not to restate the full implementation history.
The goal is to record:
- what is now consistent enough
- what is intentionally inconsistent but acceptable for now
- what should be prioritized next if ORBIT continues consistency cleanup work

Filesystem mutation now also has a meaningful consistency checkpoint because the family extends beyond exact-text and exact-hunk edits into a first strict unified-patch surface.

---

## 1. What is now consistent enough

### Discovery / search
The discovery/search family is now consistent enough to be treated as a real active surface:
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `glob`
- `search_files`
- `grep`
- `read_file`

Current consistency wins:
- `glob`, `search_files`, and `grep` all now support continuation/pagination semantics where appropriate
- `glob` now accepts `path` as the preferred alias while preserving `base_path` compatibility
- `search_files` remains the lighter content-discovery primitive
- `grep` now exists as a separate richer content-search capability rather than silently overloading `search_files`
- discovery/search capabilities now exist at all major layers:
  - filesystem MCP server
  - governance
  - provider exposure
  - SessionManager runtime truth
  - docs / knowledge-base truth

### Planning / todo
The planning family is now consistent enough to count as a real first slice:
- `todo_write`
- `todo_read`

Current consistency wins:
- explicit structured todo contract
- session-scoped truth is now implemented rather than hypothetical
- runtime/session integration is validated
- provider exposure is present
- docs now correctly describe it as a session-scoped first slice rather than a missing family

### Web / docs retrieval
The retrieval family is now consistent enough to count as a real first slice:
- `web_fetch`

Current consistency wins:
- retrieval-only posture is explicit
- bounded output contract is explicit
- runtime/server/provider/docs layers are aligned
- network-policy stance is now documented instead of merely implied

### Filesystem mutation
The mutation family is now consistent enough to treat exact-edit and first-slice patching as one governed surface:
- `write_file`
- `replace_in_file`
- `replace_all_in_file`
- `replace_block_in_file`
- `apply_exact_hunk`
- `apply_unified_patch`

Current consistency wins:
- strict mutation semantics remain separate from read/discovery semantics
- unified patch application now has a canonical MCP entry instead of requiring decomposition into lower-level edits first
- SessionManager grounding-aware write gating now covers `apply_unified_patch` in the same family as the other filesystem mutation tools
- first-slice patch failure semantics remain structured (`patch_path_mismatch`, `hunk_context_mismatch`, `overlapping_hunks`) instead of collapsing into one opaque tool failure

---

## 2. What is intentionally inconsistent but acceptable for now

### A. Mixed naming styles
Current families still mix:
- camelCase (`maxResults`, `maxDepth`, `sortBy`)
- snake_case (`max_chars`, `head_limit`, `output_mode`, `extract_main_text`)

Current stance:
- keep compatibility
- prefer `snake_case` for richer/newer capability parameters
- do not perform breaking renames just for style purity

### B. CLI-shaped grep fields
`grep` still uses some CLI-shaped keys:
- `-A`
- `-B`
- `-i`
- `-n`

Current stance:
- acceptable for now because they map clearly to ripgrep-like semantics
- future aliases can be added if a more model-friendly surface becomes desirable

### C. Capability placement inside the filesystem MCP server
The filesystem MCP server now hosts:
- filesystem discovery / mutation
- todo first slice
- web_fetch first slice

Current stance:
- acceptable for the current expansion phase
- not necessarily the long-term final server partitioning

---

## 3. Highest-value cleanup actions still remaining

### Priority 1 — Keep local-resource naming centered on `path`
Current stance is now explicit:
- `path` should be the preferred canonical local-resource parameter
- `glob.base_path` survives only as a legacy-compatible alias

Possible next step:
- extend this stance carefully via aliases/normalization rather than disruptive renames

### Priority 2 — Prevent SessionManager special-case sprawl
Current SessionManager logic now contains capability-specific branches for:
- `glob`
- `grep`
- `todo_*`

This is acceptable today but should be watched.
Possible next step:
- collect these special cases into a clearer capability-dispatch note or helper layer before they sprawl further

### Priority 3 — Continue `grep` runtime-quality polish
Canonical `grep` now exists and is real.
The remaining work is not introduction, but polish:
- result-envelope consistency
- richer failure metadata consistency
- possible alias cleanup for CLI-shaped fields
- repo-scale behavior refinement over time

### Priority 4 — Clarify long-term network policy for `web_fetch`
Current stance is now documented.
What remains is deciding whether later hardening should add:
- localhost / private-network restrictions
- stricter redirect rules
- host-trust distinctions

### Priority 5 — Decide whether todo truth remains session-scoped
Current planning surface is intentionally lightweight.
The next planning question is whether ORBIT should later add:
- a more persistent planning substrate
- a shared/workspace-level todo truth
- or keep todo intentionally session-local

---

## 4. Recommended next-action order

If ORBIT continues consistency cleanup rather than opening a new major capability line immediately, the best next order is:

1. keep `path`-first naming stance stable and avoid new drift
2. prevent SessionManager special-case growth from becoming ad hoc architecture
3. polish canonical `grep`
4. revisit `web_fetch` trust hardening only when real use cases justify it
5. revisit planning persistence only when session-scoped todo becomes a real constraint

---

## 5. Bottom line

After this cleanup wave, ORBIT's new capability families are no longer merely implemented.
They are now mostly aligned across:
- server implementation
- governance
- provider exposure
- runtime validation
- project documentation

The remaining work is now mostly polish, boundary clarification, and architecture discipline — not basic capability absence.
