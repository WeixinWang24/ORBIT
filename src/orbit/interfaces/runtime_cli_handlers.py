"""Input handling helpers for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from .adapter_protocol import RuntimeCliAdapter
from .input import ParsedKey
from .pty_runtime_router import activate_chat, activate_approvals, activate_sessions, attach_current_session, cycle_inspect_tab, hop_inspect_session, submit_composer
from .runtime_cli_state import RETURN_TO_CHAT_BANNER, RuntimeCliState


def scroll_up(state: RuntimeCliState) -> None:
    state.content_scroll = max(0, state.content_scroll - 1)


def scroll_down(state: RuntimeCliState) -> None:
    state.content_scroll += 1


def chat_scroll_up(state: RuntimeCliState) -> None:
    state.content_scroll += 1


def chat_scroll_down(state: RuntimeCliState) -> None:
    state.content_scroll = max(0, state.content_scroll - 1)


def reset_scroll(state: RuntimeCliState) -> None:
    state.content_scroll = 0


def is_printable_text_key(event: ParsedKey) -> bool:
    if event.ctrl or event.meta or event.fn or event.shift:
        return False
    name = event.name
    if len(name) != 1:
        return False
    if name in {"\x1b", "\t", "\r", "\n", "\x00", "�"}:
        return False
    code = ord(name)
    if code < 32 or code == 127:
        return False
    if not name.isprintable():
        return False
    allowed_ascii = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 `~!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?")
    if code < 128:
        return name in allowed_ascii
    return True


def handle_chat_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    name = event.name
    if name == "enter":
        submit_composer(state, adapter)
        reset_scroll(state)
        return True
    if name == "backspace":
        state.composer_text = state.composer_text[:-1]
        return False
    if name in {"up", "pageup"}:
        chat_scroll_up(state)
        return False
    if name in {"down", "pagedown"}:
        chat_scroll_down(state)
        return False
    if name == "home":
        state.content_scroll = 10**9
        return False
    if name == "end":
        state.content_scroll = 0
        return False
    if is_printable_text_key(event):
        state.composer_text += name
        return False
    return False


def handle_sessions_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    sessions = adapter.list_sessions()
    name = event.name
    if name == "c":
        activate_chat(state, RETURN_TO_CHAT_BANNER)
        reset_scroll(state)
    elif name in ("a", "A"):
        activate_approvals(state)
        reset_scroll(state)
    elif name in ("j", "down"):
        state.selected_session = min(len(sessions) - 1, state.selected_session + 1)
    elif name in ("k", "up"):
        state.selected_session = max(0, state.selected_session - 1)
    elif name == "enter":
        attach_current_session(state, adapter)
        reset_scroll(state)
    return False


def handle_approvals_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    approvals = adapter.list_open_approvals()
    name = event.name
    if name == "c":
        activate_chat(state, RETURN_TO_CHAT_BANNER)
        reset_scroll(state)
    elif name in ("s", "S"):
        activate_sessions(state)
        reset_scroll(state)
    elif name in ("j", "down") and approvals:
        state.selected_approval = min(len(approvals) - 1, state.selected_approval + 1)
    elif name in ("k", "up") and approvals:
        state.selected_approval = max(0, state.selected_approval - 1)
    return False


def handle_inspect_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    name = event.name
    if name == "c":
        activate_chat(state, RETURN_TO_CHAT_BANNER)
        reset_scroll(state)
    elif name in {"up", "pageup"}:
        scroll_up(state)
    elif name in {"down", "pagedown"}:
        scroll_down(state)
    elif name in ("t", "tab") and not event.shift:
        cycle_inspect_tab(state)
        reset_scroll(state)
    elif name == "tab" and event.shift:
        cycle_inspect_tab(state, reverse=True)
        reset_scroll(state)
    elif name == "j":
        hop_inspect_session(state, adapter)
        reset_scroll(state)
    elif name == "k":
        hop_inspect_session(state, adapter, reverse=True)
        reset_scroll(state)
    return False


def handle_info_panel_key(state: RuntimeCliState, event: ParsedKey) -> bool:
    name = event.name
    if name == "c":
        activate_chat(state, RETURN_TO_CHAT_BANNER)
        reset_scroll(state)
    elif name in {"up", "pageup", "j"}:
        scroll_up(state)
    elif name in {"down", "pagedown", "k"}:
        scroll_down(state)
    elif name == "home":
        state.content_scroll = 10**9
    elif name == "end":
        state.content_scroll = 0
    return False
