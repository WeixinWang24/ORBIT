"""Rendering helpers for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from . import termio as T
from .adapter_protocol import RuntimeCliAdapter
from .pty_primitives import terminal_size
from .pty_text import divider, fit_text, header_text, wrap_text
from .pty_runtime_router import current_session_id
from .runtime_cli_state import (
    APPROVALS_MODE,
    CHAT_MODE,
    HELP_MODE,
    INSPECT_ARTIFACTS_TAB,
    INSPECT_EVENTS_TAB,
    INSPECT_MODE,
    INSPECT_TOOL_CALLS_TAB,
    INSPECT_TRANSCRIPT_TAB,
    SESSIONS_MODE,
    STATUS_MODE,
    RuntimeCliState,
)

INSPECT_TAB_LABELS = {
    INSPECT_TRANSCRIPT_TAB: "transcript",
    INSPECT_EVENTS_TAB: "events",
    INSPECT_TOOL_CALLS_TAB: "tool_calls",
    INSPECT_ARTIFACTS_TAB: "artifacts",
}


def session_row(session, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain = fit_text(f"{prefix}{session.session_id}  {session.backend_name}/{session.model}  {session.status}", width)
    return (T.INVERSE + plain + T.RESET) if selected else plain


def approval_row(approval, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain = fit_text(f"{prefix}{approval.tool_name}  {approval.session_id}  {approval.status}", width)
    if selected:
        return T.INVERSE + plain + T.RESET
    return T.FG_YELLOW + plain + T.RESET


def tab_bar(tab_index: int) -> str:
    parts = []
    for index, name in INSPECT_TAB_LABELS.items():
        if index == tab_index:
            parts.append(f"{T.INVERSE}{T.BOLD} {name} {T.RESET}")
        else:
            parts.append(f"{T.DIM} {name} {T.RESET}")
    return "│".join(parts)


def chat_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    session_id = current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    lines = [
        state.banner,
        T.DIM + f"session={session.session_id}  backend={session.backend_name}/{session.model}" + T.RESET,
        divider(width),
    ]
    body: list[str] = []
    for msg in adapter.list_messages(session_id):
        label = msg.role.upper() if not msg.message_kind else f"{msg.role.upper()} [{msg.message_kind}]"
        color = T.FG_BRIGHT_BLUE if msg.role == "user" else T.FG_BRIGHT_GREEN if msg.role == "assistant" else T.FG_YELLOW
        body.append(color + label + T.RESET)
        for ln in wrap_text(msg.content, max(20, width - 2)):
            body.append("  " + ln)
        body.append("")
    if not body:
        body.append(T.DIM + "No messages yet. Type below and press Enter." + T.RESET)
    return lines + body


def help_body_lines(adapter: RuntimeCliAdapter, width: int) -> list[str]:
    lines = [header_text("Slash Help", width), divider(width)]
    for line in adapter.slash_help_page().splitlines():
        lines.extend(wrap_text(line, max(20, width - 2)))
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k scroll · c back to chat · Ctrl+C quit" + T.RESET)
    return lines


def status_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    lines = [header_text("Status", width), divider(width)]
    session_id = current_session_id(state, adapter)
    payload = [
        f"session={session_id}",
        f"mode={state.mode}",
        f"inspect_tab={INSPECT_TAB_LABELS.get(state.tab_index, state.tab_index)}",
        f"composer_len={len(state.composer_text)}",
        f"scroll={state.content_scroll}",
        "",
        str(adapter.get_workbench_status()),
    ]
    for line in payload:
        lines.extend(wrap_text(line, max(20, width - 2)))
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓ scroll · c back to chat · Ctrl+C quit" + T.RESET)
    return lines


def sessions_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    sessions = adapter.list_sessions()
    lines = [header_text("Sessions", width), divider(width)]
    for i, session in enumerate(sessions):
        lines.append(session_row(session, i == state.selected_session, width))
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k move · Enter attach · a approvals · c back · Ctrl+C quit" + T.RESET)
    return lines


def approvals_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    approvals = adapter.list_open_approvals()
    lines = [header_text("Approvals", width), divider(width)]
    if not approvals:
        lines.append(T.DIM + "No pending approvals." + T.RESET)
    else:
        state.selected_approval = min(state.selected_approval, len(approvals) - 1)
        for i, approval in enumerate(approvals):
            lines.append(approval_row(approval, i == state.selected_approval, width))
        current = approvals[state.selected_approval]
        lines += [
            divider(width),
            T.FG_YELLOW + current.tool_name + T.RESET + T.DIM + f"  session={current.session_id}" + T.RESET,
            T.DIM + f"approval_request_id={current.approval_request_id}" + T.RESET,
            T.DIM + f"status={current.status}  side_effect={current.side_effect_class}" + T.RESET,
            *(wrap_text(current.summary, max(20, width - 2))),
        ]
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k move · /approve [note] · /reject [note] · s sessions · c back · Ctrl+C quit" + T.RESET)
    return lines


def inspect_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    session_id = current_session_id(state, adapter)
    tab = INSPECT_TAB_LABELS[state.tab_index]
    lines = [
        header_text(f"Inspect · {session_id}", width),
        divider(width),
        tab_bar(state.tab_index),
        divider(width),
    ]
    body: list[str] = []
    if tab == "events":
        for ev in adapter.list_events(session_id):
            body.append(T.FG_CYAN + ev.event_type + T.RESET)
            body.extend("  " + ln for ln in wrap_text(str(ev.payload), max(20, width - 2)))
            body.append("")
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            body.append(T.BOLD + call.tool_name + T.RESET)
            body.append(T.DIM + f"  status={call.status}" + T.RESET)
            body.extend("  " + ln for ln in wrap_text(call.summary, max(20, width - 2)))
            body.append("")
    elif tab == "artifacts":
        for art in adapter.list_artifacts(session_id):
            body.append(T.FG_MAGENTA + art.artifact_type + T.RESET)
            body.extend("  " + ln for ln in wrap_text(art.content, max(20, width - 2)))
            body.append("")
    else:
        for msg in adapter.list_messages(session_id):
            label = msg.role if not msg.message_kind else f"{msg.role}/{msg.message_kind}"
            color = T.FG_BRIGHT_BLUE if msg.role == "user" else T.FG_BRIGHT_GREEN if msg.role == "assistant" else T.FG_YELLOW
            body.append(color + label + T.RESET)
            body.extend("  " + ln for ln in wrap_text(msg.content, max(20, width - 2)))
            body.append("")
    lines += body
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓ scroll · t/Tab next · Shift+Tab prev · j/k session hop · c back · Ctrl+C quit" + T.RESET)
    return lines


def body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    if state.mode == HELP_MODE:
        return help_body_lines(adapter, width)
    if state.mode == STATUS_MODE:
        return status_body_lines(state, adapter, width)
    if state.mode == SESSIONS_MODE:
        return sessions_body_lines(state, adapter, width)
    if state.mode == APPROVALS_MODE:
        return approvals_body_lines(state, adapter, width)
    if state.mode == INSPECT_MODE:
        return inspect_body_lines(state, adapter, width)
    return chat_body_lines(state, adapter, width)


def composer_line(state: RuntimeCliState, width: int) -> str:
    if state.mode == CHAT_MODE:
        prefix = T.FG_BRIGHT_CYAN + "[INPUT] > " + T.RESET
        body = state.composer_text or "Type message or /command"
    else:
        prefix = T.DIM + "[NAV] " + T.RESET
        body = "Navigation mode"
    return prefix + fit_text(body, max(1, width - 8))


def frame_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter) -> list[str]:
    width, height = terminal_size()
    session_id = current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    if state.mode == CHAT_MODE:
        title = f"ORBIT · Agent Runtime Chat · {session_id} · {session.backend_name}/{session.model}"
    elif state.mode == INSPECT_MODE:
        title = f"ORBIT · Inspector · {INSPECT_TAB_LABELS[state.tab_index]} · {session_id}"
    elif state.mode == APPROVALS_MODE:
        title = f"ORBIT · Approvals · {session_id}"
    elif state.mode == SESSIONS_MODE:
        title = "ORBIT · Sessions"
    elif state.mode == HELP_MODE:
        title = "ORBIT · Slash Help"
    else:
        title = f"ORBIT · Status · {session_id}"
    header = [header_text(title, width)]
    footer = [divider(width), composer_line(state, width)]
    body = body_lines(state, adapter, width)
    available = max(4, height - len(header) - len(footer))
    max_scroll = max(0, len(body) - available)
    state.content_scroll = max(0, min(state.content_scroll, max_scroll))
    if state.mode == CHAT_MODE:
        body = body[max(0, len(body) - available - state.content_scroll): len(body) - state.content_scroll if state.content_scroll > 0 else len(body)]
    else:
        body = body[state.content_scroll: state.content_scroll + available]
    return header + body + footer
