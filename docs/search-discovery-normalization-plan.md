# Search / Discovery Normalization Plan

## Why this plan exists

Initial planning risked treating search/discovery as an entirely missing MCP family.
The asset audit showed that this is not accurate.

ORBIT already has significant discovery surface inside the filesystem MCP server:
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `search_files`
- `read_file`

The next move is therefore normalization and gap-filling, not wholesale reinvention.

## Goal

Turn the existing filesystem discovery/read assets into a more explicit coding-agent discovery surface, then fill the most obvious missing capability.

## Existing discovery/read capabilities

### Directory and path discovery
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `glob`

### Content discovery
- `search_files`

### File read
- `read_file`

## Most obvious gap

### Missing canonical `glob`

This gap is now closed in the current first normalization wave.
ORBIT now has an explicit canonical glob-style discovery tool inside the filesystem MCP server.
The remaining question is not whether glob exists, but whether its first-slice contract is sufficient for coding-agent discovery work.

## Plan

### Step 1 — Normalize the discovery surface conceptually

Document and treat the following as the current discovery surface:
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`
- `search_files`
- `read_file`

This matters because coding-agent planning should not pretend these capabilities are absent.

### Step 2 — Add canonical `glob`

This step is now completed in the current first normalization wave.

Current first-slice `glob` contract:
- workspace-scoped
- bounded-result
- pagination-aware via `offset`
- now accepts `path` as the preferred alias for the glob root
- still accepts `base_path` as a legacy-compatible alias during the normalization transition
- returns structured matches including:
  - `path`
  - `kind`
  - `name`
- returns:
  - `path`
  - `base_path`
  - `pattern`
  - `offset`
  - `matches`
  - `match_count`
  - `truncated`

This means ORBIT now has a usable file/path pattern discovery primitive rather than only directory/tree/list views.

### Step 3 — Reassess `search_files`

This step has now partially advanced.

`search_files` currently remains:
- a filesystem-flavored bounded content search
- substring-based rather than explicit regex/grep semantics
- pagination-aware via `offset`

Current first-slice conclusion:
- do **not** rename or replace `search_files` yet
- treat it as the current content-discovery primitive
- defer a grep-quality promotion decision until ORBIT has more real coding-agent usage against the combined surface of:
  - `glob`
  - `search_files`
  - `read_file`
  - `directory_tree`

The unresolved future question is therefore narrower now:
- not “ORBIT needs search from zero”
- but “should `search_files` stay a filesystem-flavored bounded content search or later become a more explicit grep-like capability?”

Current evaluation result:
- do **not** silently mutate `search_files` into grep semantics
- keep `search_files` as the current paginated bounded content-discovery primitive
- if ORBIT needs regex/file-filter/mode-rich search later, add a distinct canonical `grep` capability rather than overloading `search_files`

### Step 3.5 — Explicitly recognize symbol/navigation as part of the current surface

This is now also important for accurate capability narration.

The filesystem MCP server does not only expose directory/content discovery primitives.
It now also includes an active canonical code-navigation first slice:
- `get_symbols_overview`
- `find_symbol`
- `find_references`
- `read_symbol_body`

Current support posture:
- Python support is stronger and more mature
- TypeScript/JavaScript support is now present in a real first slice
- TS/JS parity remains partial rather than absent
- symbol/body-read disambiguation has now begun to close the loop through optional `container` filtering in `find_symbol` and `read_symbol_body`

This means ORBIT should no longer describe the filesystem surface as discovery/read/search only.
The more accurate current framing is:
- discovery
- file/content search
- code navigation first slice

The remaining open question is therefore not whether symbol/navigation exists, but how far ORBIT should continue polishing multi-language code navigation beyond the current first slice.

Important current boundary:
- `find_symbol` and `read_symbol_body` now support optional `container` filtering for disambiguation
- `find_references` intentionally does not yet claim container-qualified filtering, because its current first slice is still a candidate-reference surface rather than a fully resolved symbol-ownership graph

Current naming-consistency stance:
- `path` should remain the preferred canonical local-resource parameter across discovery/search tools
- `glob.base_path` is now treated as a legacy-compatible alias rather than the preferred long-term naming posture
- existing camelCase fields like `maxResults` / `maxDepth` remain compatible for now
- newly added richer capability parameters may continue using `snake_case` where that better reflects unit semantics or avoids awkward CLI-to-tool translation

Related operational note:
- `web_fetch` currently follows a separate retrieval-oriented naming style (`url`, `max_chars`, `format_hint`, `extract_main_text`) because it is not a filesystem-local discovery tool and its bounds are content-size oriented rather than result-count oriented

### Step 4 — Only then decide on a distinct discovery MCP family

Do not create a separate discovery server unless normalization pressure justifies it.
The default assumption should be:
- filesystem discovery remains under the filesystem server
- coding-agent discovery is a higher-level interpretation over existing capabilities plus a few targeted additions

## Success condition

This normalization step is successful when:
- ORBIT can clearly state what its discovery surface already is
- `glob` is added as the missing high-frequency capability
- discovery primitives use bounded-result contracts consistently enough for coding-agent exploration
- `glob` and `search_files` both support pagination-aware continuation via `offset`
- the role of `search_files` is narrowed explicitly even if final grep-promotion is still deferred
- coding-agent roadmap planning no longer underestimates existing filesystem discovery assets

## Current status

Current status after the first normalization wave:
- discovery surface is now explicitly:
  - `list_directory`
  - `list_directory_with_sizes`
  - `get_file_info`
  - `directory_tree`
  - `glob`
  - `search_files`
  - `read_file`
- `glob` now exists and is integrated through MCP registry, governance, and SessionManager runtime truth
- `glob` supports `offset` pagination and structured match metadata
- `search_files` now also supports `offset` pagination while remaining intentionally substring-based and filesystem-flavored
- canonical `grep` first slice now also exists as a distinct richer content-search capability
- `grep` currently supports regex-style content search with:
  - `output_mode` (`content`, `files_with_matches`, `count`)
  - `glob`
  - `type`
  - `-i`
  - `-n`
  - `-A` / `-B` / `context`
  - `head_limit`
  - `offset`
  - `multiline`
- current `grep` implementation prefers real `rg` when available and falls back to a bounded Python implementation when `rg` is absent
- canonical `grep` first slice is now also validated through SessionManager same-turn closure and pagination paths, not only server-level tests
- the remaining unresolved question is no longer grep absence, but how far ORBIT should continue polishing canonical `grep` toward a fuller repo-scale search surface
- canonical symbol/navigation first slice is now also explicitly part of the active filesystem surface: `get_symbols_overview`, `find_symbol`, `find_references`, and `read_symbol_body`
- current symbol/navigation posture is multi-language but uneven: Python is stronger, while TS/JS support is present as a partial first slice rather than absent
