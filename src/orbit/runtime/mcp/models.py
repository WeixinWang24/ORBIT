from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


McpTransportKind = Literal["stdio", "unix_socket"]
McpContinuityMode = Literal["stateless", "persistent_preferred", "persistent_required"]

# ---------------------------------------------------------------------------
# Capability metadata Literal types — first-slice, small and hard.
# These encode the architecture-level posture of each MCP family, not
# runtime state. All fields use closed Literal sets to catch declaration
# drift at type-check time.
# ---------------------------------------------------------------------------

McpCapabilityFamily = Literal["browser", "process", "diagnostics", "filesystem", "git", "bash"]

# How does continuity of meaningful state work for this family?
McpContinuityType = Literal[
    "live_host",         # live browser session — state lives in the host process
    "persisted_task",    # persisted runner/output files — survives server restarts
    "bounded_result",    # one-shot invocation → bounded result object
    "session_semantic",  # continuity comes from session-scoped metadata
    "stateless",         # no continuity required; each call is independent
]

# Where does authoritative truth come from for this family?
McpTruthSource = Literal[
    "live_host_state",              # live browser host process
    "persisted_runtime_artifacts",  # runner status file + stdout/stderr files + store
    "bounded_result_object",        # structured result returned by the tool call itself
    "session_metadata",             # session-scoped metadata record
    "filesystem_or_repo_truth",     # underlying filesystem or git repo state
]

# What architectural role does this family play in the runtime layer stack?
McpLayerRole = Literal[
    "substrate",       # core execution environment (process, browser, filesystem)
    "interpretation",  # interprets substrate output (diagnostics: pytest, ruff, mypy)
    "access_support",  # facilitates access to substrate (git, bash)
]

# How important is MCP transport continuity (persistent server process) for correctness?
McpTransportImportance = Literal[
    "required",    # correctness depends on the live MCP server process (browser)
    "preferred",   # reuse improves efficiency; correctness does not depend on it (process)
    "irrelevant",  # MCP server process lifecycle has no bearing on correctness
]


@dataclass(frozen=True)
class McpCapabilityMetadata:
    """
    First-slice capability posture metadata for one MCP family.

    Declared explicitly by each bootstrap function — not inferred by the runtime.
    Frozen to prevent accidental mutation after construction.
    All fields are required (no defaults): every declaration must be complete.
    """
    capability_family: McpCapabilityFamily
    continuity_type: McpContinuityType
    truth_source: McpTruthSource
    layer_role: McpLayerRole
    transport_importance: McpTransportImportance


@dataclass
class McpStdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    continuity_mode: McpContinuityMode = "stateless"
    # Capability posture metadata. Optional so that servers that have not yet
    # declared metadata (e.g., obsidian) do not require a declaration.
    capability_metadata: McpCapabilityMetadata | None = None


@dataclass
class McpClientBootstrap:
    server_name: str
    normalized_name: str
    tool_prefix: str
    transport: McpTransportKind
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    continuity_mode: McpContinuityMode = "stateless"
    # Propagated from McpStdioServerConfig at bootstrap time. Visible to
    # registry_loader and McpToolWrapper so the runtime can inspect posture
    # without reconstructing it from server name or continuity_mode heuristics.
    capability_metadata: McpCapabilityMetadata | None = None

    # --- Daemon/socket transport fields (used when transport="unix_socket") ---
    # Path to the Unix domain socket the daemon listens on.
    socket_path: str | None = None
    # Deterministic identity key for the running daemon instance. Used by
    # lifecycle management to decide whether an existing daemon can be reused
    # or must be restarted (e.g., after code or config changes).
    server_instance_key: str | None = None


@dataclass
class McpToolDescriptor:
    server_name: str
    original_name: str
    orbit_tool_name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
