"""Rendering helpers for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

from dataclasses import dataclass
from unicodedata import east_asian_width

from . import termio as T
from .adapter_protocol import RuntimeCliAdapter
from .chat_projection import build_chat_projection
from .chat_viewport_state import compute_chat_viewport
from .composer_state import display_width as composer_display_width, render_composer
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

@dataclass
class FrameRender:
    lines: list[str]
    composer_row: int
    composer_col: int


ACCENT_PRIMARY = T.FG_BRIGHT_MAGENTA
ACCENT_SECONDARY = T.FG_BRIGHT_CYAN
ACCENT_MUTED = T.FG_BRIGHT_BLACK
ACCENT_SUCCESS = T.FG_BRIGHT_GREEN
ACCENT_WARNING = T.FG_BRIGHT_YELLOW

INSPECT_TAB_LABELS = {
    INSPECT_TRANSCRIPT_TAB: "transcript",
    INSPECT_EVENTS_TAB: "events",
    INSPECT_TOOL_CALLS_TAB: "tool_calls",
    INSPECT_ARTIFACTS_TAB: "artifacts",
}


def session_row(session, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain = fit_text(f"{prefix}{session.session_id}  {session.backend_name}/{session.model}  {session.status}", width)
    return (ACCENT_PRIMARY + T.INVERSE + plain + T.RESET) if selected else ACCENT_MUTED + plain + T.RESET


def approval_row(approval, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain = fit_text(f"{prefix}{approval.tool_name}  {approval.session_id}  {approval.status}", width)
    if selected:
        return ACCENT_PRIMARY + T.INVERSE + plain + T.RESET
    return ACCENT_WARNING + plain + T.RESET


def tab_bar(tab_index: int) -> str:
    parts = []
    for index, name in INSPECT_TAB_LABELS.items():
        if index == tab_index:
            parts.append(f"{ACCENT_PRIMARY}{T.INVERSE}{T.BOLD} {name} {T.RESET}")
        else:
            parts.append(f"{ACCENT_MUTED}{T.DIM} {name} {T.RESET}")
    return "│".join(parts)


def chat_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    session_id = current_session_id(state, adapter)
    projection = build_chat_projection(
        adapter=adapter,
        session_id=session_id,
        width=width,
        runtime_busy=state.runtime_busy,
        pending_submit_session_id=state.pending_submit_session_id,
        pending_submit_text=state.pending_submit_text,
        submit_started_at=state._submit_thread_started_at,
        assistant_inflight_text=state.assistant_inflight_text,
        accent_user=ACCENT_SECONDARY,
        accent_assistant=ACCENT_PRIMARY,
        accent_warning=ACCENT_WARNING,
        accent_muted=ACCENT_MUTED,
        approval_picker_index=state.approval_picker_index,
    )
    return projection.lines


def help_body_lines(adapter: RuntimeCliAdapter, width: int) -> list[str]:
    lines = [header_text("Slash Help", width), divider(width)]
    for line in adapter.slash_help_page().splitlines():
        lines.extend(wrap_text(line, max(20, width - 2)))
    lines += [
        "",
        ACCENT_PRIMARY + T.BOLD + "Current PTY navigation keys" + T.RESET,
        "  c → return to chat",
        "  h → open help from navigation modes",
        "  i → return to inspect from help/status",
        "  t / Tab → next inspect tab",
        "  Shift+Tab → previous inspect tab",
        "  j / k → move or hop depending on mode",
        "  Enter → attach / submit / confirm depending on mode",
        "  Ctrl+C → quit",
    ]
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k scroll · i inspect · c back to chat · Ctrl+C quit" + T.RESET)
    return lines


def status_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    lines = [header_text("Status", width), divider(width)]
    session_id = current_session_id(state, adapter)
    payload = adapter.get_workbench_status()
    status_lines = [
        f"session={session_id}",
        f"active_session_id={state.active_session_id}",
        f"selected_session={state.selected_session}",
        f"mode={state.mode}",
        f"inspect_tab={INSPECT_TAB_LABELS.get(state.tab_index, state.tab_index)}",
        f"composer_len={len(state.composer.text)}",
        f"scroll={state.content_scroll}",
        f"chat_viewport.scroll_offset={state.chat_viewport.scroll_offset}",
        f"runtime_busy={state.runtime_busy}",
        f"pending_submit_session_id={state.pending_submit_session_id}",
        "",
        f"adapter_kind={payload.get('adapter_kind')}",
        f"session_count={payload.get('session_count')}",
        f"approval_count={payload.get('approval_count')}",
        f"registered_tool_count={payload.get('registered_tool_count')}",
        "registered_tools:",
    ]
    for line in status_lines:
        lines.extend(wrap_text(line, max(20, width - 2)))
    for name in payload.get("registered_tool_names", [])[:16]:
        lines.extend(wrap_text(f"  - {name}", max(20, width - 2)))
    remaining = len(payload.get("registered_tool_names", [])) - 16
    if remaining > 0:
        lines.extend(wrap_text(f"  ... (+{remaining} more)", max(20, width - 2)))
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
            ACCENT_WARNING + current.tool_name + T.RESET + T.DIM + f"  session={current.session_id}" + T.RESET,
            T.DIM + f"approval_request_id={current.approval_request_id}" + T.RESET,
            T.DIM + f"status={current.status}  side_effect={current.side_effect_class}" + T.RESET,
            *(wrap_text(current.summary, max(20, width - 2))),
        ]
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k move · a approve · r reject · /approve [note] · /reject [note] · s sessions · c back · Ctrl+C quit" + T.RESET)
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
            body.append(ACCENT_SECONDARY + ev.event_type + T.RESET)
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
            body.append(ACCENT_PRIMARY + art.artifact_type + T.RESET)
            body.extend("  " + ln for ln in wrap_text(art.content, max(20, width - 2)))
            body.append("")
    else:
        for msg in adapter.list_messages(session_id):
            label = msg.role if not msg.message_kind else f"{msg.role}/{msg.message_kind}"
            color = ACCENT_SECONDARY if msg.role == "user" else ACCENT_PRIMARY if msg.role == "assistant" else ACCENT_WARNING
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


def composer_lines(state: RuntimeCliState, width: int, *, pulse_tick: int | None = None) -> tuple[list[str], int, int]:
    rendered = render_composer(state.composer, width=width, chat_mode=(state.mode == CHAT_MODE), pulse_tick=pulse_tick if state.mode == CHAT_MODE else None)
    return rendered.lines, rendered.cursor_row_offset, max(1, min(width, rendered.cursor_col))


def build_chat_header(state: RuntimeCliState, session, width: int) -> list[str]:
    import time

    title = ACCENT_SUCCESS + f"ORBIT · Agent Runtime Chat · {session.session_id} · {session.backend_name}/{session.model}" + T.RESET
    lines = [
        header_text(title, width),
        fit_text(state.banner, width),
    ]
    if state.runtime_busy:
        busy_for = ""
        if state._submit_thread_started_at is not None:
            busy_for = f" · busy_for={max(0.0, time.time() - state._submit_thread_started_at):.1f}s"
        lines.append(ACCENT_WARNING + fit_text(f"runtime busy{busy_for}", width) + T.RESET)
    lines.extend([
        T.DIM + fit_text(f"session={session.session_id}  backend={session.backend_name}/{session.model}", width) + T.RESET,
        divider(width),
    ])
    return lines


def build_chat_footer(state: RuntimeCliState, width: int, pulse_tick: int) -> tuple[list[str], int, int]:
    composer_footer, composer_row_offset, composer_col = composer_lines(state, width, pulse_tick=pulse_tick)
    return [divider(width), *composer_footer], composer_row_offset, composer_col


def build_chat_frame(state: RuntimeCliState, adapter: RuntimeCliAdapter, *, width: int, height: int, pulse_tick: int) -> FrameRender:
    session_id = current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    header = build_chat_header(state, session, width)
    footer, composer_row_offset, composer_col = build_chat_footer(state, width, pulse_tick)
    header_height = len(header)
    footer_height = len(footer)
    body_lines_full = chat_body_lines(state, adapter, width)
    available_body_height = max(1, height - header_height - footer_height)
    viewport = compute_chat_viewport(
        lines=body_lines_full,
        viewport_height=available_body_height,
        state=state.chat_viewport,
    )
    body = viewport.visible_lines
    lines = header + body + footer
    max_frame_lines = max(1, height)
    if len(lines) > max_frame_lines:
        body_budget = max(0, max_frame_lines - header_height - footer_height)
        body = body[-body_budget:] if body_budget > 0 else []
        lines = header + body + footer
    composer_row = len(lines) - (len(footer) - 1 - composer_row_offset) + 1
    return FrameRender(lines=lines, composer_row=composer_row, composer_col=max(1, composer_col))


def frame_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter | None) -> FrameRender:
    import time
    width, height = terminal_size()
    pulse_tick = int(time.time())
    if adapter is None or state.startup_loading:
        title = ACCENT_SUCCESS + "ORBIT · Agent Runtime Chat · starting..." + T.RESET
        header = [header_text(title, width), state.banner, divider(width)]
        body = [
            T.DIM + "Runtime UI is live. Loading runtime adapter and initial session in the background..." + T.RESET
        ]
        if state.startup_error:
            body.extend(["", T.FG_YELLOW + f"startup_error={state.startup_error}" + T.RESET])
        composer_footer, composer_row_offset, composer_col = composer_lines(state, width, pulse_tick=pulse_tick)
        footer = [divider(width), *composer_footer]
        available = max(4, height - len(header) - len(footer))
        body = body[:available]
        lines = header + body + footer
        composer_row = len(lines) - (len(composer_footer) - 1 - composer_row_offset)
        return FrameRender(lines=lines, composer_row=composer_row, composer_col=max(1, composer_col))
    if state.mode == CHAT_MODE:
        return build_chat_frame(state, adapter, width=width, height=height, pulse_tick=pulse_tick)
    session_id = current_session_id(state, adapter)
    if state.mode == INSPECT_MODE:
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
    composer_footer, composer_row_offset, composer_col = composer_lines(state, width, pulse_tick=pulse_tick)
    footer = [divider(width), *composer_footer]
    body = body_lines(state, adapter, width)
    available = max(4, height - len(header) - len(footer))
    max_scroll = max(0, len(body) - available)
    state.content_scroll = max(0, min(state.content_scroll, max_scroll))
    body = body[state.content_scroll: state.content_scroll + available]
    lines = header + body + footer
    composer_row = len(lines) - (len(composer_footer) - 1 - composer_row_offset)
    return FrameRender(lines=lines, composer_row=composer_row, composer_col=max(1, composer_col))
