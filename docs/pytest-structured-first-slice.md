# run_pytest_structured — First Slice

## Status

Implemented. First-slice scope. Not a full CI orchestration or diagnostics platform.

---

## What This Is

`run_pytest_structured` is ORBIT's first structured diagnostics tool.

It occupies the layer between:
- **`run_bash`** — raw shell execution, unstructured output
- **a future broader diagnostics family** — not built yet, not needed now

Its purpose is to give a coding agent a better-structured feedback loop for the
edit → run tests → inspect failures → refine cycle. Raw shell output is still
available via `run_bash`; `run_pytest_structured` exists specifically for test
execution where structured summary and failure surface matter.

---

## What It Is Not

- Not a full CI/CD orchestration layer
- Not a test analytics platform
- Not a coverage, mypy, or ruff integration
- Not a flaky-test detection system
- Not a browser-driven test harness
- Not a multi-language diagnostics suite

If you need to add any of those, add them separately. Do not expand this tool.

---

## Tool Contract

**Name:** `run_pytest_structured`  
**Server:** `pytest`  
**Governance:** `safe` / `system_environment` / no approval required

### Inputs

| Field            | Type       | Required | Description |
|-----------------|------------|----------|-------------|
| `path`          | string     | No       | Workspace-relative directory or file to scope the pytest run. Ignored if `targets` is provided. |
| `targets`       | string[]   | No       | Explicit pytest node IDs to run. Takes priority over `path`. |
| `keyword`       | string     | No       | `-k` expression to filter tests by name pattern. |
| `max_failures`  | integer    | No       | `--maxfail=N`: stop after N failures. |
| `timeout_seconds` | number   | No       | Execution timeout (default 60s, max 300s). |

### Result Shape

```json
{
  "success": true,
  "exit_code": 0,
  "timed_out": false,
  "counts": {
    "collected": 5,
    "passed": 5,
    "failed": 0,
    "skipped": 0,
    "errors": 0,
    "warnings": null,
    "duration_seconds": 0.12
  },
  "failures": [],
  "failures_total": 0,
  "failures_truncated": false,
  "raw_output_excerpt": "...(bounded)...",
  "raw_output_truncated": false,
  "parse_confidence": "full",
  "invocation": {
    "cwd": "/path/to/workspace",
    "path": null,
    "targets": [],
    "keyword": null,
    "max_failures": null,
    "command": "python -m pytest --tb=short --no-header -v"
  }
}
```

When tests fail, the `failures` array contains bounded records:

```json
{
  "failures": [
    {
      "node_id": "tests/test_foo.py::TestFoo::test_bar",
      "headline": "AssertionError: assert 1 == 2",
      "excerpt": "    def test_bar():\n>       assert 1 == 2\nE       AssertionError...",
      "excerpt_truncated": false
    }
  ]
}
```

### Key Fields

**`success`** — overall pass/fail. True if exit_code is 0 or 5 (no tests collected).  
**`parse_confidence`** — `"full"` | `"partial"` | `"minimal"`. Honest signal about how much was actually parsed.  
**`failures_total`** — total number of FAILED/ERROR entries found (may exceed `len(failures)` if truncated).  
**`failures_truncated`** — True if more than 20 failures were found (first 20 returned).  
**`excerpt_truncated`** — True per failure if the traceback body was capped at 2000 chars.  
**`raw_output_excerpt`** — full stdout (or stderr if no stdout), capped at 8000 chars.

---

## Implementation Architecture

### Files

```
src/mcp_servers/system/core/pytest/stdio_server.py   — MCP server + parser
src/orbit/runtime/mcp/pytest_bootstrap.py            — bootstrap wiring
src/orbit/runtime/mcp/governance.py                  — governance entry
src/orbit/runtime/core/session_manager.py            — enable_mcp_pytest flag
src/orbit/interfaces/runtime_adapter.py              — RuntimeAdapterConfig flag
tests/test_pytest_structured_first_slice.py          — 48 tests
```

### How It Works

1. `invoke_pytest()` builds a `pytest --tb=short --no-header -v` command
2. Runs as a bounded subprocess (scrubbed environment, explicit timeout)
3. Text parser extracts structure from stdout/stderr:
   - `parse_collected()` — "collected N items" line
   - `parse_summary_counts()` — final "N passed, M failed in Xs" line
   - `parse_short_summary_items()` — "FAILED node_id - reason" lines from short summary section
   - `parse_failure_blocks()` — full failure bodies from FAILURES section
   - `build_failure_records()` — combines short summary + failure blocks into bounded records
4. Returns structured JSON with honest `parse_confidence` signal

### Parser Approach

Text parsing against stable pytest output conventions (`--tb=short`). This is more
robust than depending on a third-party plugin like `pytest-json-report`. The parser
is explicit about what it found vs. what it didn't: any field that was not parsed
is `null`, not fabricated.

`parse_confidence`:
- `"full"` — summary counts AND short summary failure items both parsed
- `"partial"` — counts parsed but failure details are best-effort
- `"minimal"` — only exit code available (e.g., internal error, corrupted output)

### Governance

`run_pytest_structured` is classified as `safe` / `system_environment` / no approval.
This is a deliberate first-slice decision: test execution is a verification step in
the coding workflow, and requiring approval on every test run would break the coding
loop. The tool is workspace-scoped and timeout-bounded.

Note: test execution does run code and writes `.pytest_cache/`; these are accepted as
benign for this use case.

---

## Bounds and Safety

| Concern | Bound |
|---------|-------|
| Max failures returned | 20 (configurable in implementation) |
| Max excerpt per failure | 2000 chars |
| Max raw output excerpt | 8000 chars |
| Max timeout | 300 seconds |
| Default timeout | 60 seconds |
| cwd | always workspace_root |
| path scope | workspace-relative, validated against workspace boundary |
| target sanitization | rejects `..` traversal and shell metacharacters |
| environment | scrubbed (API keys stripped via `build_scrubbed_subprocess_env`) |

---

## Remaining First-Slice Limitations

These are intentional scope boundaries, not bugs:

- **No coverage integration** — no `--cov` flags, no coverage report parsing
- **No mypy/ruff/lint** — diagnostics are pytest-only
- **No historical tracking** — results are ephemeral, not stored
- **No parallel test execution** — always single-threaded pytest invocation
- **No pytest plugin support** — only standard pytest output is parsed
- **No interactive/PTY mode** — subprocess capture only; progress streamed only at end
- **No per-test timing data** — duration is the total run time only
- **Parametrized test matching** — failure block matching to node IDs is fuzzy for parametrized tests; `excerpt` may be empty for some parametrized cases
- **Collection errors** — counted as failures at the invocation level; individual errored files are not separately itemized in the `failures` array

---

## What a Future Diagnostics Family Would Add

When this first slice is too limiting:
- Coverage integration (`run_coverage_structured`)
- Lint/type-check integration (`run_mypy_structured`, `run_ruff_structured`)
- Parallel execution control
- Structured per-test timing
- Collection error itemization
- Persistent result storage for trend analysis

None of those are part of this first slice.
