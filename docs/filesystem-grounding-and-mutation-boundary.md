# Filesystem Grounding and Mutation Boundary

## Purpose
This note formalizes ORBIT's current runtime invariant for filesystem mutation safety.

The core principle is:

> Permission allow is necessary but not sufficient for mutation.
> Mutation also requires adequate grounding quality.

ORBIT now treats filesystem grounding as a first-class runtime substrate rather than an informal side effect of prior path access.

---

## Why this exists

ORBIT's filesystem capability family began as a read-oriented tool surface.
As the family expanded, it became important to distinguish between:

- path familiarity
- partial vs full read truth
- fresh vs stale grounding
- permission approval vs semantic readiness to mutate

This note captures the current ORBIT answer:
filesystem mutation should depend on both governance approval and grounding quality.

---

## Layer model

### 1. Grounding observation layer
ORBIT records session-scoped filesystem read state in `session.metadata["filesystem_read_state"]`.

Current observed fields include:
- `source_tool`
- `timestamp_epoch`
- `is_partial_view`
- `grounding_kind`
- `path_kind`
- `observed_modified_at_epoch`
- `observed_size_bytes`
- `range`

Current grounding participation is intentionally narrow:
- `read_file` participates
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `search_files`
  do not currently contribute grounding state

### 2. Grounding classification layer
ORBIT currently derives explicit per-path grounding status via:
- `filesystem_grounding_status_for_path(...)`

Current statuses are:
- `none`
- `partial_only`
- `full_read_fresh`
- `full_read_stale`

These statuses distinguish whether ORBIT has enough trustworthy grounding to treat a path as semantically ready for future mutation consideration.

### 3. Mutation readiness layer
ORBIT currently derives mutation-facing readiness via:
- `filesystem_write_readiness_for_path(...)`

Current reasons are:
- `no_prior_grounding`
- `partial_read_grounding_insufficient`
- `stale_full_read_grounding`
- `full_read_fresh_grounding_available`

This layer converts grounding classification into mutation eligibility semantics.

### 4. Execution boundary layer
ORBIT now applies the readiness layer to real execution for:
- `native__write_file`
- `native__replace_in_file`

Current invariant:
- approval remains necessary for grounded mutation tools such as `native__write_file` and `native__replace_in_file`
- approval does not bypass grounding checks
- insufficient or stale grounding produces an explicit visible tool failure
- successful execution still requires both approval and fresh full-read grounding

---

## Explicit runtime behavior

### Read optimization
ORBIT supports an explicit `filesystem_unchanged` result for repeated same-path `read_file` requests only when:
- prior grounding is `full_read`
- the file still matches recorded `observed_modified_at_epoch`
- the file still matches recorded `observed_size_bytes`

Partial grounding does not qualify.
The shortcut is explicit and inspectable, not silent.

### Mutation gating
For `native__write_file` and `native__replace_in_file`, ORBIT now blocks mutation when write readiness is not eligible.
The blocked path is surfaced as a tool-visible failure with grounding-readiness metadata rather than hidden fallback behavior.

---

## Current boundaries
This note describes what ORBIT currently does, not what it has already generalized.

Current boundaries:
- grounded mutation now covers `native__write_file` and the first minimal edit-family path `native__replace_in_file`
- richer edit/diff-style mutation families are not yet grounded-aware
- hash-based freshness evidence is not yet implemented
- range-aware grounding identity is not yet implemented
- ORBIT does not yet auto-recover by forcing a reread when grounding is stale
- non-read filesystem tools still do not contribute mutation grounding

---

## Design consequence
This architecture establishes a durable ORBIT invariant:

> Permission and policy decide whether mutation may be attempted.
> Grounding quality decides whether mutation is semantically ready to proceed.

That distinction is now part of ORBIT runtime truth, not just roadmap language.

---

## Next likely extensions
Future work may extend this boundary through:
- richer edit/diff mutation families
- broader grounding participation rules
- stronger freshness evidence such as content hashes
- range-aware read identity
- explicit stale-grounding recovery paths

The important rule for future work is to preserve the current layering rather than collapsing approval, freshness, and mutation readiness into one opaque decision.
