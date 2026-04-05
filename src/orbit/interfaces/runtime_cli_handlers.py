"""Input handling helpers for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from .adapter_protocol import RuntimeCliAdapter
from .input import ParsedKey
from .pty_runtime_router import activate_chat, activate_approvals, activate_help, activate_inspect, activate_sessions, attach_current_session, cycle_inspect_tab, hop_inspect_session, resolve_current_approval, resolve_current_approval_via_picker, submit_composer
from .runtime_cli_state import INSPECT_TRANSCRIPT_TAB, RETURN_TO_CHAT_BANNER, RuntimeCliState


def scroll_up(state: RuntimeCliState) -> None:
    state.content_scroll = max(0, state.content_scroll - 1)


def scroll_down(state: RuntimeCliState) -> None:
    state.content_scroll += 1


def chat_scroll_up(state: RuntimeCliState) -> None:
    state.chat_viewport.anchor_to_bottom = False
    state.chat_viewport.scroll_offset += 1


def chat_scroll_down(state: RuntimeCliState) -> None:
    state.chat_viewport.scroll_offset = max(0, state.chat_viewport.scroll_offset - 1)
    if state.chat_viewport.scroll_offset == 0:
        state.chat_viewport.anchor_to_bottom = True


def reset_scroll(state: RuntimeCliState) -> None:
    state.content_scroll = 0
    state.chat_viewport.scroll_offset = 0


def is_printable_text_key(event: ParsedKey) -> bool:
    if event.sequence.startswith("\x1b"):
        return False
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
    current_session = adapter.get_session(state.active_session_id) if state.active_session_id else None
    pending = adapter.get_pending_approval(current_session.session_id) if current_session is not None else None
    has_pending_approval = pending is not None
    composer_has_text = bool(state.composer.text.strip())

    if has_pending_approval:
        if name == "enter":
            if state.approval_action_pending:
                return True
            if composer_has_text and state.composer.text.strip().startswith("/"):
                state.banner = f"Submitting {len(state.composer.text.strip())} chars to active session..."
                submit_composer(state, adapter)
                reset_scroll(state)
                return True
            selection = resolve_current_approval_via_picker(state, adapter)
            if selection is None:
                reset_scroll(state)
                return True
            decision, reauth_tool_name, reauth_note = selection
            state.approval_action_pending = True
            state.approval_action_label = "Approving..." if decision == "approve" else "Denying..."
            state.banner = state.approval_action_label
            state.pending_submit_session_id = current_session.session_id if current_session is not None else None
            state.pending_submit_text = ""
            state.runtime_busy = True
            state.completed_submit_banner = None
            state.completed_submit_error = None
            state.composer.text = ""
            setattr(state, "_pending_approval_resolution", {
                "decision": decision,
                "reauth_tool_name": reauth_tool_name,
                "reauth_note": reauth_note,
            })
            reset_scroll(state)
            return True
        if state.approval_action_pending:
            return True
        if name in {"up", "k"}:
            state.approval_picker_index = max(0, state.approval_picker_index - 1)
            return True
        if name in {"down", "j"}:
            state.approval_picker_index = min(2, state.approval_picker_index + 1)
            return True
        if composer_has_text and not state.composer.text.strip().startswith("/") and name in {"backspace"}:
            state.composer.backspace()
            return False
        if composer_has_text and not state.composer.text.strip().startswith("/"):
            # keep picker focus semantics; free typing only matters for slash commands here
            if is_printable_text_key(event):
                state.composer.insert_text(name)
            return True

    if name == "enter":
        if state.runtime_busy and not has_pending_approval:
            state.banner = "Runtime busy; you can keep typing, but submit waits for the current turn to finish."
            return True
        state.banner = f"Submitting {len(state.composer.text.strip())} chars to active session..."
        submit_composer(state, adapter)
        reset_scroll(state)
        return True
    if name == "tab":
        state.composer.insert_newline()
        return False
    if name == "backspace":
        state.composer.backspace()
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
        state.composer.insert_text(name)
        return False
    return False


def handle_sessions_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    sessions = adapter.list_sessions()
    name = event.name
    if name in ("h", "H"):
        activate_help(state)
        reset_scroll(state)
    elif name == "c":
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
    if name in ("h", "H"):
        activate_help(state)
        reset_scroll(state)
    elif name == "c":
        activate_chat(state, RETURN_TO_CHAT_BANNER)
        reset_scroll(state)
    elif name in ("s", "S"):
        activate_sessions(state)
        reset_scroll(state)
    elif name in ("j", "down") and approvals:
        state.selected_approval = min(len(approvals) - 1, state.selected_approval + 1)
    elif name in ("k", "up") and approvals:
        state.selected_approval = max(0, state.selected_approval - 1)
    elif name in ("a", "A") and approvals:
        resolve_current_approval(state, adapter, "approve")
        reset_scroll(state)
        return True
    elif name in ("r", "R") and approvals:
        resolve_current_approval(state, adapter, "reject")
        reset_scroll(state)
        return True
    return False


def handle_inspect_key(state: RuntimeCliState, adapter: RuntimeCliAdapter, event: ParsedKey) -> bool:
    name = event.name
    if name in ("h", "H"):
        activate_help(state)
        reset_scroll(state)
    elif name == "c":
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
    if name in ("i", "I"):
        activate_inspect(state, INSPECT_TRANSCRIPT_TAB)
        reset_scroll(state)
    elif name in ("h", "H"):
        activate_help(state)
        reset_scroll(state)
    elif name == "c":
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
