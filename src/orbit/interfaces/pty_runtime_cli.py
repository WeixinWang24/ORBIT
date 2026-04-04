"""Runtime-first raw PTY CLI that uses `pty_workbench.py` as the interaction/visual reference.

Design rule:
- functionality reference: runtime-first raw runtime workbench / chat-first shell
- interaction + display reference: `pty_workbench.py`
"""

from __future__ import annotations

from .adapter_protocol import RuntimeCliAdapter
from .chat_mock_adapter import MockOrbitChatAdapter
from .runtime_adapter import RuntimeAdapterConfig, SessionManagerRuntimeAdapter
from . import termio as T
from .input import ParsedFocus, ParsedKey, ParsedMouse, parse_sequence, read_sequence
from .pty_debug import debug_log
from .pty_primitives import ScreenBuffer, alt_screen, bracketed_paste, focus_events, mouse_tracking, raw_mode, terminal_size
from .runtime_cli_handlers import handle_approvals_key, handle_chat_key, handle_info_panel_key, handle_inspect_key, handle_sessions_key
from .runtime_cli_render import frame_lines
from .runtime_cli_state import APPROVALS_MODE, CHAT_MODE, HELP_MODE, INSPECT_MODE, RuntimeCliState, SESSIONS_MODE, STATUS_MODE


def _build_default_adapter() -> RuntimeCliAdapter:
    try:
        adapter = SessionManagerRuntimeAdapter.build(RuntimeAdapterConfig())
        if not adapter.list_sessions():
            adapter.create_session()
        debug_log("pty_runtime_cli:using_session_manager_runtime_adapter")
        return adapter
    except Exception as exc:
        debug_log(f"pty_runtime_cli:runtime_adapter_fallback={exc!r}")
        adapter = MockOrbitChatAdapter()
        if not adapter.list_sessions():
            adapter.create_session()
        return adapter


def browse_runtime_cli(adapter: RuntimeCliAdapter | None = None) -> None:
    debug_log("pty_runtime_cli:start")
    adapter = adapter or _build_default_adapter()
    state = RuntimeCliState()
    screen = ScreenBuffer()
    in_paste = False

    with raw_mode(), alt_screen(), mouse_tracking(), bracketed_paste(), focus_events():
        while True:
            width, height = terminal_size()
            screen.render(frame_lines(state, adapter), width, height)
            raw = read_sequence()
            if not raw:
                debug_log("pty_runtime_cli:raw=<empty>")
                continue
            debug_log(f"pty_runtime_cli:raw={raw!r}")
            if raw == T.PASTE_START:
                in_paste = True
                continue
            if raw == T.PASTE_END:
                in_paste = False
                continue
            if in_paste:
                continue

            event = parse_sequence(raw)
            debug_log(f"pty_runtime_cli:mode={state.mode} event={event!r}")
            if event is None:
                continue

            if isinstance(event, ParsedFocus):
                screen.invalidate()
                continue
            if isinstance(event, ParsedMouse):
                continue
            if not isinstance(event, ParsedKey):
                continue

            name = event.name
            ctrl = event.ctrl
            if name == "escape":
                debug_log(f"pty_runtime_cli:swallow_escape mode={state.mode}")
                continue
            if ctrl and name == "c":
                screen.invalidate()
                screen.render([T.DIM + "Exited ORBIT runtime CLI." + T.RESET], width, 1)
                return

            invalidate = False
            if state.mode == CHAT_MODE:
                invalidate = handle_chat_key(state, adapter, event)
            elif state.mode == SESSIONS_MODE:
                handle_sessions_key(state, adapter, event)
            elif state.mode == APPROVALS_MODE:
                handle_approvals_key(state, adapter, event)
            elif state.mode == INSPECT_MODE:
                handle_inspect_key(state, adapter, event)
            elif state.mode in {HELP_MODE, STATUS_MODE}:
                handle_info_panel_key(state, event)

            if invalidate:
                screen.invalidate()
