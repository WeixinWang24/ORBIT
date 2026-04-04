"""State objects and shared mode semantics for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from dataclasses import dataclass

CHAT_MODE = "chat"
SESSIONS_MODE = "sessions"
APPROVALS_MODE = "approvals"
HELP_MODE = "help"
INSPECT_MODE = "inspect"
STATUS_MODE = "status"

INSPECT_TRANSCRIPT_TAB = 0
INSPECT_EVENTS_TAB = 1
INSPECT_TOOL_CALLS_TAB = 2
INSPECT_ARTIFACTS_TAB = 3
INSPECT_TAB_ORDER = [
    INSPECT_TRANSCRIPT_TAB,
    INSPECT_EVENTS_TAB,
    INSPECT_TOOL_CALLS_TAB,
    INSPECT_ARTIFACTS_TAB,
]

DEFAULT_CHAT_BANNER = "Agent Runtime mode · slash commands available via /help"
RETURN_TO_CHAT_BANNER = "Returned to agent runtime chat"
CREATED_SESSION_BANNER = "Created new session"
ATTACH_FAILED_BANNER = "Attach failed"
UNKNOWN_COMMAND_BANNER = "Unknown slash command"


@dataclass
class RuntimeShellState:
    """Shared shell state for slash routing and runtime workbench navigation."""

    mode: str = CHAT_MODE
    selected_session: int = 0
    selected_approval: int = 0
    tab_index: int = INSPECT_TRANSCRIPT_TAB
    show_help_overlay: bool = False
    composer_text: str = ""
    banner: str = DEFAULT_CHAT_BANNER


@dataclass
class RuntimeCliState(RuntimeShellState):
    """Runtime-first PTY CLI state, including scroll position."""

    content_scroll: int = 0
