# ORBIT Project Structure

## Root-level organization rule

The ORBIT repository should keep the root directory intentionally small.
Whenever possible, files should be grouped into functionally coherent directories rather than left scattered at the project root.

## Source organization preference

At each directory level, ORBIT should try to avoid having more than five loose files when a clearer functional grouping is available.
This is a readability preference rather than a rigid mathematical law, but it should guide refactors and new additions.

## Current root-level groups

- `apps/` — runnable application entrypoints
- `config/` — environment and configuration artifacts
- `docs/` — repository-facing documentation
- `notebooks/` — notebook-first demonstrations
- `notes/` — local demo/support notes used by scaffold scenarios
- `src/` — importable ORBIT source code

## Second-level grouping examples

- `docs/architecture/` — architecture notes
- `docs/setup/` — environment and setup instructions
- `docs/persistence/` — persistence direction notes
- `notebooks/runtime/` — runtime/approval demos
- `notebooks/workbench/` — workbench/operator demos
- `notebooks/providers/` — provider-route demos
- `notes/scaffold/` — scaffold helper text files
- `src/orbit/runtime/core/` — core runtime coordination files
- `src/orbit/runtime/execution/` — execution-layer files
- `src/orbit/runtime/auth/oauth/` — OAuth flow helpers
- `src/orbit/runtime/auth/storage/` — stored auth material helpers
- `src/orbit/runtime/execution/contracts/` — execution contracts
- `src/orbit/runtime/execution/engines/` — execution engines
- `src/orbit/notebook/display/` — projection/display helpers
- `src/orbit/notebook/providers/` — provider-specific notebook helpers
- `src/orbit/notebook/workbench/` — workbench-specific notebook helpers

## Practical interpretation

This is not a rule for pointless nesting.
The goal is not maximum folder depth; the goal is to reduce clutter and keep related code discoverable.

Naming consistency matters, but ORBIT should prefer navigation clarity over churn-heavy renames.
If a name is already clear and locally coherent, avoid renaming it just to make every directory use exactly the same word shape.
