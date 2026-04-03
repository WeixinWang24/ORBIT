# Prompt / Context Assembly MVP

This note defines the first provider-agnostic prompt/context layering model for ORBIT's active SessionManager-centered runtime.

## Guiding principle

**Model world is not runtime world.**

Therefore ORBIT must not let:
- provider-model self-description
- provider brand/vendor labels
- one provider's payload schema

silently define ORBIT's internal context taxonomy.

ORBIT should instead define its own internal context layers first, then project them into each backend's provider-facing payload shape.

## Scope separation

### Session scope
Session scope contains what the conversational participant should see or continue from.

Examples:
- user messages
- assistant messages
- tool results
- approval request / approval decision transcript artifacts
- selected transcript-visible runtime-failure artifacts

### Runtime scope
Runtime scope contains execution/inspection/control facts that the runtime must know without automatically making them part of session-visible conversation.

Examples:
- auth failures
- runtime events
- context/payload snapshots
- control metadata
- adapter-specific payload contracts
- debugging/inspection artifacts

## First internal context layers

### 1. Identity / charter layer
What kind of agent ORBIT is, what it is for, and what behavior boundaries it should respect.

Current examples:
- ORBIT workbench identity
- high-level behavioral constraints
- governance posture summary

### 2. Project / workspace layer
Project-specific guidance that belongs to the current working environment rather than the global runtime identity.

Current future target examples:
- ORBIT project instructions
- workspace conventions
- local development guidance
- project architecture reminders

### 3. Runtime mode layer
Turn/session execution mode constraints.

Examples:
- text-only mode
- tool-enabled mode
- inspection/debug mode
- approval-sensitive mode

### 4. Session continuity layer
What the current session already established.

Examples:
- transcript-derived history context
- active pending approval state
- governed tool state summary where needed for planning
- previous visible assistant commitments

### Transcript vs history rule

Transcript remains the canonical visible conversation truth.

However, for prompt/context assembly purposes, ORBIT should derive a separate **history context element** from transcript truth so history can later participate in the same assembly/budgeting/compression pipeline as other context elements.

This means:
- canonical transcript truth is not discarded or demoted
- history in prompt assembly is treated as a derived context element rather than a privileged special-case transport forever
- future compression/summarization/retrieval-aware context engineering can operate on history through the same assembly discipline used for other context sources

### 5. Retrieval / memory layer
Context brought in from outside the immediate visible transcript.

Examples:
- curated memory
- retrieval results
- knowledge snippets
- future long-term memory summaries

### 6. Turn-specific overlay layer
Ephemeral instructions or constraints for the current turn only.

Examples:
- continuation bridge
- rejection continuation hint
- temporary debug instruction
- turn-scoped execution hint

## Projection rule

These layers are internal ORBIT context layers.
They are **not** identical to the final provider-facing payload.

For example:
- a Codex backend may project high-level instruction layers into a single `instructions` field plus an `input` transcript projection
- a chat-completions-style backend may project some of the same layers into `system`/`user`/`assistant` role-structured messages
- another backend may project them in a different provider-specific shape

To support this cleanly, ORBIT should introduce a provider-agnostic assembly plan between internal layers and final provider payload.

## PromptAssemblyPlan direction

A `PromptAssemblyPlan` should become the next explicit intermediate structure between runtime context assembly and provider payload projection.

Its role is to answer, provider-agnostically:
- which fragments belong to high-priority instruction space
- which fragments belong to transcript/session continuity space
- which fragments are auxiliary model-visible context
- which fragments are runtime-only and should not enter provider-visible prompt space
- what projection hints may help a backend map these fragments into its specific schema

### Why this matters

This prevents ORBIT from letting one provider's convenient field structure define the long-term internal prompt taxonomy.

### Early projection examples

- **Codex-style projection**
  - instruction-domain fragments -> merged into `instructions`
  - transcript/session continuity -> projected into `input`

- **Chat-completions-style projection**
  - instruction-domain fragments -> one or more high-priority `system` messages
  - transcript/session continuity -> projected into role-structured conversation messages

The assembly plan should stay internal and provider-agnostic; only the final projection step should become provider-schema-specific.

## Canonical vs derived

### Canonical
- transcript/history for visible conversation truth
- session runtime control state for control truth

### Derived observation artifacts
- context assembly snapshot
- provider payload snapshot

These snapshots help debugging and inspection, but they do not become canonical source-of-truth layers themselves.

## Immediate next-step implication

The next implementation step should define a first explicit assembly object owned by the runtime before provider projection, so ORBIT can inspect:
- which internal layers contributed to a turn
- what effective instruction text was assembled
- how that assembly was projected into the provider payload
