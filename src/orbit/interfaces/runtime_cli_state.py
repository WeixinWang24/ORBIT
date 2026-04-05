"""State objects and shared mode semantics for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

from .chat_viewport_state import ChatViewportState
from .composer_state import ComposerState

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
    active_session_id: str | None = None
    selected_approval: int = 0
    tab_index: int = INSPECT_TRANSCRIPT_TAB
    show_help_overlay: bool = False
    composer: ComposerState = field(default_factory=ComposerState)
    chat_viewport: ChatViewportState = field(default_factory=ChatViewportState)
    banner: str = DEFAULT_CHAT_BANNER


@dataclass
class RuntimeCliState(RuntimeShellState):
    """Runtime-first PTY CLI state, including scroll position."""

    content_scroll: int = 0
    runtime_busy: bool = False
    pending_submit_session_id: str | None = None
    pending_submit_text: str = ""
    assistant_inflight_text: str | None = None
    assistant_inflight_dirty: bool = False
    completed_submit_banner: str | None = None
    completed_submit_error: str | None = None
    approval_picker_index: int = 0
    _submit_thread_started_at: float | None = None
    startup_loading: bool = True
    startup_error: str | None = None
