# MCP Adapter Layering Design

## Purpose
This note defines the intended layering for MCP integration inside ORBIT.

It is written after:
- validating the first Python-first filesystem MCP capability family on the active SessionManager mainline
- extending the MCP read surface to include a first read-only git capability family (`git_status`, `git_diff`, `git_log`, `git_show`)
- hardening the current SessionManager/governance/tool runtime boundaries
- absorbing external lessons about tool runtime design, capability adaptation, and hook/permission invariants

This note is not a claim that every layer below is already fully implemented. It is the design frame ORBIT should use as MCP integration grows beyond the current minimal filesystem slice.

---

## Core statement
MCP should be treated as an external capability substrate, not as a parallel tool world.

That means:
- MCP transport/session/auth concerns belong to one layer
- MCP capability discovery and schema/result adaptation belong to another layer
- the active ORBIT runtime should expose one unified ToolRegistry truth to provider payload construction, execution, persistence, and inspection

In short:
- external capability source
- internal runtime contract
- one execution/governance truth

---

## Layer model

### Layer 1 — MCP transport/session/auth
Responsibilities:
- start/connect to stdio/http/ws MCP endpoints
- manage transport/session lifecycle
- represent connection states (`connecting`, `connected`, `failed`, `needs_auth`, etc.)
- apply timeouts/retries/reconnect where appropriate

Current ORBIT examples:
- `src/orbit/runtime/mcp/client.py`
- `src/orbit/runtime/mcp/bootstrap.py`

Design rule:
- this layer should not decide product-facing tool semantics by itself
- it exists to make external capability endpoints usable and observable

---

### Layer 2 — capability adaptation
Responsibilities:
- discover MCP tools/resources/prompts
- normalize external names/descriptions/schemas/results into ORBIT-understandable capability objects
- preserve canonical MCP naming where appropriate
- attach source metadata (`tool_source`, `server_name`, `original_name`, etc.)

Current ORBIT examples:
- `src/orbit/runtime/mcp/client.py`
- `src/orbit/runtime/mcp/registry_loader.py`
- `src/orbit/tools/mcp.py`

Design rule:
- this layer should adapt external capability surfaces into ORBIT-native runtime objects
- it should not bypass governance, transcript, artifact, or invocation pipelines

---

### Layer 3 — ORBIT-facing tool runtime contract
Responsibilities:
- present one assembled ToolRegistry truth to the active runtime
- expose tools consistently to:
  - provider payload construction
  - SessionManager execution
  - tool invocation persistence
  - inspector surfaces
- apply native and MCP tools under the same runtime contract shape as much as possible

Current ORBIT examples:
- `src/orbit/tools/registry.py`
- `src/orbit/runtime/core/session_manager.py`
- shared registry injection into `openai_codex.py`

Design rule:
- ORBIT should not allow provider payload exposure and execution truth to drift apart
- runtime-assembled tool surfaces must be shared, not rebuilt in parallel subsystems

---

### Layer 4 — governance / approval / policy insertion points
Responsibilities:
- canonicalize governance-relevant inputs before evaluation
- apply permission/policy/approval boundaries
- distinguish policy deny vs tool execution failure
- preserve failed/denied attempts as runtime-visible truth where appropriate

Current ORBIT examples:
- `src/orbit/runtime/core/session_manager.py`
- `src/orbit/runtime/mcp/governance.py`

Design rule:
- governance invariant must remain stronger than transport details, hooks, extension points, or convenience wrappers
- MCP integration must pass through the same governance system rather than escaping it

---

### Layer 5 — result / artifact / observation projection
Responsibilities:
- normalize raw MCP results into ORBIT tool results
- preserve structured-first outputs where possible
- support transcript-visible summaries without turning transcript into a bulk data bus
- persist tool invocations and artifacts for inspector/debug/runtime truth

Current ORBIT examples:
- `src/orbit/tools/base.py`
- `src/orbit/tools/mcp.py`
- `src/orbit/web_inspector.py`
- store-level tool invocation persistence

Design rule:
- raw result, normalized runtime result, transcript-visible summary, and artifact storage are related but distinct concerns
- large or rich MCP outputs should eventually be governed by explicit artifact/result policy rather than implicit transcript sprawl

---

## Truth ownership

### Single most important rule
There must be one assembled ToolRegistry truth per active runtime/session context.

That assembled registry should be the source used by:
- provider payload tool exposure
- SessionManager execution lookup
- tool invocation persistence naming
- inspector/tool-call rendering

This rule already proved necessary during the filesystem MCP slice, where provider payload construction initially drifted from execution truth until a shared registry was injected.

---

## Naming policy

### Native tools
Native tools are explicitly source-tagged.
Examples:
- `native__read_file`
- `native__write_file`

### MCP tools
MCP-exposed tools should preserve canonical/original names where possible.
Examples:
- `read_file`
- `list_directory`
- `list_directory_with_sizes`
- `get_file_info`
- `directory_tree`

Design rule:
- canonical names should be preferred for protocol-compatible external capability surfaces
- source-tagging is primarily an ORBIT-native implementation concern, not something that should be forced onto MCP tool names by default

---

## Result policy

As MCP capability coverage grows, ORBIT should explicitly distinguish at least four result shapes:

1. **raw external result**
   - what the MCP server actually returned
2. **normalized ORBIT tool result**
   - structured-first, governance-compatible, runtime-visible
3. **transcript-visible summary/result message**
   - concise enough for conversation truth
4. **artifact-backed large/rich output**
   - future path for large trees/search results/blob/image-heavy outputs

This design direction aligns with ORBIT’s current structured-first tool result posture and future filesystem runtime-quality roadmap.

---

## Resource/prompt distinction

Future MCP growth should not flatten everything into “just tools.”

At minimum, ORBIT should be ready to distinguish:
- callable tools
- readable resources
- prompt-like or command-like external surfaces

Why this matters:
- these have different semantics
- they likely need different governance and observation behavior
- they should not all be modeled as the same object forever

---

## Relationship to filesystem runtime quality roadmap

The filesystem roadmap and this MCP adapter design are complementary.

### Filesystem runtime quality roadmap answers:
- how filesystem results/grounding/freshness should mature

### MCP adapter layering design answers:
- how external capabilities should enter the ORBIT runtime without creating a second tool world

Together they form the intended ORBIT direction:
- Python-first product-native capability assets where valuable
- MCP as a capability substrate when appropriate
- one runtime truth across payload, execution, persistence, and inspection

---

## Immediate practical implications for ORBIT

### Already validated
- a Python-first local filesystem MCP capability family can be integrated into the active SessionManager mainline without splitting runtime truth
- MCP tools can share one ToolRegistry with native tools
- canonical MCP names can coexist with source-tagged native tools
- policy-denied MCP attempts can remain visible in tool-call truth

### Next likely design moves
- formalize richer tool metadata (`is_read_only`, `is_concurrency_safe`, capability family tags)
- make result/artifact policy more explicit for richer MCP outputs
- eventually separate MCP tools/resources/prompts more clearly
- keep governance insertion points central even if hook/extensibility layers are introduced later

---

## ORBIT design stance

Do not copy external runtime architectures wholesale.

Instead:
- absorb proven layering principles
- preserve ORBIT-native governance and transcript truth
- preserve structured-first outputs and inspection surfaces
- treat MCP as a substrate to be adapted, not as a sidecar universe with its own independent reality
