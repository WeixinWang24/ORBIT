"""Rendering helpers for the runtime-first ORBIT PTY CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from unicodedata import east_asian_width

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEBUG_LOG_SOURCES = [
    ("mcp_stderr",  _REPO_ROOT / ".tmp" / "mcp_stderr.log"),
    ("orbit_debug", _REPO_ROOT / ".tmp" / "orbit_pty_debug.log"),
]
_DEBUG_LOG_MAX_LINES = 2000  # cap kept in memory per render


def _read_debug_log_lines() -> list[str]:
    """Read all configured debug log files and merge into a single line list."""
    merged: list[str] = []
    for source_name, path in _DEBUG_LOG_SOURCES:
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = raw.splitlines()[-_DEBUG_LOG_MAX_LINES:]
        merged.append(f"── {source_name}  ({path}) ──")
        merged.extend(lines)
        merged.append("")
    if not merged:
        merged = ["(no debug log entries yet — logs appear here once MCP subprocesses run)"]
    return merged

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
    INSPECT_DEBUG_TAB,
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


# Label accents — high-brightness, used for role headers (USER / ASSISTANT).
ACCENT_PRIMARY   = T.FG_BRIGHT_MAGENTA          # assistant label
ACCENT_SECONDARY = T.fg_rgb(120, 185, 255)      # user label — bright blue, same hue as CONTENT_USER
ACCENT_MUTED     = T.FG_BRIGHT_BLACK
ACCENT_SUCCESS   = T.FG_BRIGHT_GREEN
ACCENT_WARNING   = T.FG_BRIGHT_YELLOW

# Content body colours — cyberpunk, low-saturation, dark-terminal-friendly.
# Applied to ordinary text lines inside each message; markdown-specific styles
# (headings, inline code, bold) still take priority within the line.
CONTENT_USER      = T.fg_rgb(90, 150, 215)   # muted steel-blue  — user body text
CONTENT_ASSISTANT = T.fg_rgb(150, 112, 198)  # muted violet      — assistant body text

INSPECT_TAB_LABELS = {
    INSPECT_TRANSCRIPT_TAB: "transcript",
    INSPECT_EVENTS_TAB: "events",
    INSPECT_TOOL_CALLS_TAB: "tool_calls",
    INSPECT_ARTIFACTS_TAB: "artifacts",
    INSPECT_DEBUG_TAB: "debug_log",
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
        content_user=CONTENT_USER,
        content_assistant=CONTENT_ASSISTANT,
        approval_picker_index=state.approval_picker_index,
        approval_action_pending=state.approval_action_pending,
        approval_action_label=state.approval_action_label,
        chat_history_limit=state.chat_history_limit,
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

    fixed_summary = [
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
        f"runtime_mode={payload.get('runtime_mode')}",
        f"workspace_root={payload.get('workspace_root')}",
        f"mode_policy_profile={payload.get('mode_policy_profile')}",
        f"active_build_id={payload.get('active_build_id')}",
        f"candidate_build_id={payload.get('candidate_build_id')}",
        f"last_known_good_build_id={payload.get('last_known_good_build_id')}",
    ]
    for line in fixed_summary:
        lines.extend(wrap_text(line, max(20, width - 2)))

    details = [
        divider(width),
        ACCENT_PRIMARY + T.BOLD + "Scrollable details" + T.RESET,
        f"session_count={payload.get('session_count')}",
        f"approval_count={payload.get('approval_count')}",
        f"registered_tool_count={payload.get('registered_tool_count')}",
        "registered_tools:",
    ]
    build_profile = payload.get('build_profile_timings') or {}
    if build_profile:
        details.extend([
            "",
            "build_profile_timings:",
            *(f"  {key}={value}" for key, value in build_profile.items()),
        ])
    session_manager_profile = payload.get('session_manager_profile_timings') or {}
    if session_manager_profile:
        details.extend([
            "",
            "session_manager_profile_timings:",
            *(f"  {key}={value}" for key, value in session_manager_profile.items()),
        ])
    startup_metrics = state.startup_metrics or payload.get('startup_metrics') or {}
    if startup_metrics:
        details.extend(["", "startup_metrics:"])
        for key, value in startup_metrics.items():
            if key in {'pty_import_profile_timings', 'runtime_adapter_import_profile_timings', 'session_manager_import_profile_timings'} and isinstance(value, dict):
                filtered = {nested_key: nested_value for nested_key, nested_value in value.items() if nested_value not in (0, 0.0, 'deferred')}
                if not filtered:
                    continue
                details.append(f"  {key}:")
                details.extend(f"    {nested_key}={nested_value}" for nested_key, nested_value in filtered.items())
            else:
                details.append(f"  {key}={value}")
    for name in payload.get("registered_tool_names", []):
        details.append(f"  - {name}")

    lines.append(divider(width))
    for line in details:
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
            ACCENT_WARNING + current.tool_name + T.RESET + T.DIM + f"  session={current.session_id}" + T.RESET,
            T.DIM + f"approval_request_id={current.approval_request_id}" + T.RESET,
            T.DIM + f"status={current.status}  side_effect={current.side_effect_class}" + T.RESET,
            *(wrap_text(current.summary, max(20, width - 2))),
        ]
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k move · a approve · r reject · /approve [note] · /reject [note] · s sessions · c back · Ctrl+C quit" + T.RESET)
    return lines


def inspect_body_lines(state: RuntimeCliState, adapter: RuntimeCliAdapter, width: int) -> list[str]:
    tab = INSPECT_TAB_LABELS[state.tab_index]

    if tab == "debug_log":
        return _debug_log_body_lines(state, width)

    session_id = current_session_id(state, adapter)
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
    lines.append(T.DIM + "Navigation: ↑↓ scroll · t/Tab next tab · Shift+Tab prev tab · j/k session hop · i debug log · c back · Ctrl+C quit" + T.RESET)
    return lines


def _debug_log_body_lines(state: RuntimeCliState, width: int) -> list[str]:
    lines = [
        header_text("Debug Log", width),
        divider(width),
        tab_bar(state.tab_index),
        divider(width),
    ]
    raw_lines = _read_debug_log_lines()
    for ln in raw_lines:
        # colour section headers
        if ln.startswith("──"):
            lines.append(ACCENT_WARNING + T.BOLD + fit_text(ln, width) + T.RESET)
        else:
            # dim ordinary log lines; highlight lines that look like errors
            low = ln.lower()
            if any(k in low for k in ("error", "traceback", "exception", "valueerror", "typeerror")):
                lines.append(T.FG_BRIGHT_RED + fit_text(ln, width) + T.RESET)
            else:
                lines.append(T.DIM + fit_text(ln, width) + T.RESET)
    lines.append(divider(width))
    lines.append(T.DIM + "Navigation: ↑↓/j/k scroll · t/Tab next tab · Shift+Tab prev tab · i inspect · c back · Ctrl+C quit" + T.RESET)
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


def _fmt_tokens(n: int) -> str:
    """Compact token count: <1000 → int, >=1000 → 1.2k, >=1_000_000 → 1.2m."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _format_context_usage(projection: dict) -> str:
    """Format context usage projection into a compact header string.

    Full format (when provider returns token data):
        Ctx 4.2k/612  Σ 18.4k/2.1k  Calls 5
    Compact format (calls counted but provider returned no token data):
        Calls 5
    Fallback (no turns yet):
        Ctx: n/a
    """
    totals = projection.get("totals") or {}
    call_count = totals.get("call_count", 0)

    if call_count == 0:
        return "Ctx: n/a"

    ti = totals.get("total_input_tokens", 0)
    to_ = totals.get("total_output_tokens", 0)

    # If the provider returned no token data at all, show call count only.
    if ti == 0 and to_ == 0:
        return f"Calls {call_count}"

    latest = projection.get("latest_call") or {}
    li = _fmt_tokens(latest.get("input_tokens", 0))
    lo = _fmt_tokens(latest.get("output_tokens", 0))
    return f"Ctx {li}/{lo}  \u03a3 {_fmt_tokens(ti)}/{_fmt_tokens(to_)}  Calls {call_count}"


def build_chat_header(state: RuntimeCliState, session, width: int, *, usage_projection: dict | None = None) -> list[str]:
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
    ctx_text = _format_context_usage(usage_projection) if usage_projection is not None else "Ctx: n/a"
    lines.extend([
        T.DIM + fit_text(f"session={session.session_id}  backend={session.backend_name}/{session.model}", width) + T.RESET,
        T.DIM + fit_text(ctx_text, width) + T.RESET,
        divider(width),
    ])
    return lines


def build_chat_footer(state: RuntimeCliState, width: int, pulse_tick: int) -> tuple[list[str], int, int]:
    composer_footer, composer_row_offset, composer_col = composer_lines(state, width, pulse_tick=pulse_tick)
    return [divider(width), *composer_footer], composer_row_offset, composer_col


def build_chat_frame(state: RuntimeCliState, adapter: RuntimeCliAdapter, *, width: int, height: int, pulse_tick: int) -> FrameRender:
    session_id = current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    # Fetch the per-session usage projection from the operation surface.
    # The render layer only consumes already-projected data; no accounting here.
    usage_projection: dict | None = None
    if session_id:
        try:
            usage_projection = adapter.get_context_usage_projection(session_id)
        except Exception:
            pass
    header = build_chat_header(state, session, width, usage_projection=usage_projection)
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
        tab_label = INSPECT_TAB_LABELS[state.tab_index]
        title = f"ORBIT · Debug Log" if tab_label == "debug_log" else f"ORBIT · Inspector · {tab_label} · {session_id}"
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
