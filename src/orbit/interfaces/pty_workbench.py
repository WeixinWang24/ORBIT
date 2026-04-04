"""PTY workbench for ORBIT Agent Runtime — enhanced TUI.

Improvements over the original bare-bones version:

  • Alternate screen (DEC 1049)    — clean enter/exit, no scroll pollution
  • Synchronized output (DEC 2026) — BSU/ESU wrap every frame (when supported)
  • Cursor hide during render      — prevents cursor flash
  • Screen buffer diffing          — only redraws lines that actually changed
  • SGR colour styling             — header, selected rows, tab bar, status badges
  • SGR mouse + scroll wheel       — navigate with mouse wheel up/down
  • Bracketed paste (DEC 2004)     — silently discards accidental pastes
  • Focus events (DEC 1004)        — force-invalidate on window focus change
  • Improved key parsing           — via input module (Kitty, modifyOtherKeys, SGR)
  • Page-up/Page-down scrolling    — in inspect view
  • Word-wrap in inspect view      — long content wraps instead of truncating
"""

from __future__ import annotations

import sys

from .mock_adapter import MockOrbitInterfaceAdapter
from . import termio as T
from .input import (
    ParsedFocus,
    ParsedKey,
    ParsedMouse,
    parse_sequence,
    read_sequence,
)
from .pty_debug import debug_log
from .pty_primitives import ScreenBuffer, alt_screen, bracketed_paste, focus_events, mouse_tracking, raw_mode, terminal_size
from .pty_text import divider, fit_text, header_text, wrap_text

SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]


# ── Styled fragments (all take plain-text *content*, apply SGR wrapper) ───────

def _header(text: str, width: int) -> str:
    return header_text(text, width)


def _tab_bar(tab_index: int) -> str:
    """Return a tab bar string.  SGR codes are non-printing; no width clipping needed."""
    parts = []
    for i, name in enumerate(SESSION_TABS):
        if i == tab_index:
            parts.append(f"{T.INVERSE}{T.BOLD} {name} {T.RESET}")
        else:
            parts.append(f"{T.DIM} {name} {T.RESET}")
    return "│".join(parts)


def _session_row(session, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain  = fit_text(
        f"{prefix}{session.session_id}  {session.backend_name}/{session.model}  {session.status}",
        width,
    )
    return (T.INVERSE + plain + T.RESET) if selected else plain


def _approval_row(approval, selected: bool, width: int) -> str:
    prefix = "▶ " if selected else "  "
    plain  = fit_text(
        f"{prefix}{approval.tool_name}  {approval.session_id}  {approval.status}",
        width,
    )
    if selected:
        return T.INVERSE + plain + T.RESET
    return T.FG_YELLOW + plain + T.RESET


# ── Screen buffer (diff renderer) ─────────────────────────────────────────────

# ── Tab content builders ──────────────────────────────────────────────────────

def _tab_preview_lines(
    adapter: MockOrbitInterfaceAdapter,
    session_id: str,
    tab: str,
    max_lines: int,
) -> list[str]:
    lines: list[str] = []
    if tab == "events":
        for ev in adapter.list_events(session_id)[-max_lines:]:
            lines.append(
                f"{T.FG_CYAN}{ev.event_type}{T.RESET}: {ev.payload}"
            )
        return lines
    if tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id)[:max_lines]:
            color = (
                T.FG_GREEN   if call.status == "success"
                else T.FG_YELLOW if call.status == "pending"
                else T.FG_RED
            )
            lines.append(
                f"{color}{call.tool_name}{T.RESET}: {call.status} · {call.summary}"
            )
        return lines
    if tab == "artifacts":
        for art in adapter.list_artifacts(session_id)[:max_lines]:
            lines.append(
                f"{T.FG_MAGENTA}{art.artifact_type}{T.RESET}: {art.content}"
            )
        return lines
    # transcript
    for msg in adapter.list_messages(session_id)[-max_lines:]:
        label = (
            msg.role if not msg.message_kind
            else f"{msg.role}/{msg.message_kind}"
        )
        color = T.FG_BRIGHT_BLUE if msg.role == "user" else T.FG_BRIGHT_GREEN
        lines.append(f"{color}{label}{T.RESET}: {msg.content}")
    return lines


# ── View line generators ──────────────────────────────────────────────────────

def _browser_lines(
    selected: int,
    tab_index: int,
    show_help: bool,
) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    width, height = terminal_size()

    if not sessions:
        return [
            _header("ORBIT PTY Workbench", width),
            "",
            T.DIM + "No sessions." + T.RESET,
        ]

    selected = min(selected, len(sessions) - 1)
    current  = sessions[selected]
    approvals = [
        a for a in adapter.list_open_approvals()
        if a.session_id == current.session_id
    ]

    help_rows    = 9 if show_help else 0
    max_sessions = max(2, min(len(sessions), max(4, height // 5)))
    # header(1) + divider(1) + "Sessions"(1) + sessions(N) + maybe_more(1)
    # + divider(1) + tab_bar(1) + info(2) + divider(1) = ~N+8 fixed rows
    fixed_rows   = max_sessions + 9 + help_rows
    preview_rows = max(4, height - fixed_rows)

    lines: list[str] = [
        _header(
            "ORBIT PTY Workbench  ·  q exit  ·  j/k↑↓ move  "
            "·  t tab  ·  a approvals  ·  enter inspect  ·  ? help",
            width,
        ),
        divider(width),
        T.BOLD + "Sessions" + T.RESET,
    ]
    for i, s in enumerate(sessions[:max_sessions]):
        lines.append(_session_row(s, i == selected, width))
    if len(sessions) > max_sessions:
        lines.append(
            T.DIM + f"  … {len(sessions) - max_sessions} more session(s)" + T.RESET
        )

    tab = SESSION_TABS[tab_index]
    lines += [
        divider(width),
        _tab_bar(tab_index),
        T.DIM + f"session={current.session_id}  conversation={current.conversation_id}" + T.RESET,
        T.DIM + f"messages={current.message_count}  approvals_here={len(approvals)}" + T.RESET,
        divider(width),
    ]
    lines += _tab_preview_lines(adapter, current.session_id, tab, preview_rows)

    if approvals:
        lines.append(divider(width))
        lines.append(T.BOLD + T.FG_YELLOW + "Pending approvals" + T.RESET)
        for a in approvals[: max(1, min(3, preview_rows // 2))]:
            lines.append(T.FG_YELLOW + f"  ⚠  {a.tool_name}: {a.summary}" + T.RESET)

    if show_help:
        lines += [
            divider(width),
            T.BOLD + "Help" + T.RESET,
            "  j / ↓          next session",
            "  k / ↑          previous session",
            "  t / Tab        next tab",
            "  Shift+Tab      previous tab",
            "  a              approval queue",
            "  Enter          inspect current session",
            "  scroll wheel   navigate sessions",
            "  q              exit",
            "  Esc            ignore / cancel",
        ]
    return lines


def _inspect_lines(
    session_id: str,
    tab: str,
    scroll_offset: int = 0,
) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    width, height = terminal_size()

    if session is None:
        return [T.FG_RED + "Session not found." + T.RESET]

    HEADER_ROWS = 4
    header: list[str] = [
        _header(
            f"Inspect  ·  {session.session_id}  ·  tab={tab}"
            "  ·  ↑↓/PgUp/PgDn scroll  ·  any other key back",
            width,
        ),
        divider(width),
        T.DIM + (
            f"backend={session.backend_name}  model={session.model}"
            f"  status={session.status}"
        ) + T.RESET,
        divider(width),
    ]

    body: list[str] = []
    if tab == "events":
        for ev in adapter.list_events(session_id):
            body.append(T.FG_CYAN + ev.event_type + T.RESET)
            for ln in wrap_text(str(ev.payload), width - 2):
                body.append(f"  {ln}")
            body.append("")
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            body.append(T.BOLD + call.tool_name + T.RESET)
            body.append(
                T.DIM
                + f"  status={call.status}  side_effect={call.side_effect_class}"
                + T.RESET
            )
            for ln in wrap_text(str(call.payload), width - 2):
                body.append(f"  {ln}")
            body.append("")
    elif tab == "artifacts":
        for art in adapter.list_artifacts(session_id):
            body.append(
                T.FG_MAGENTA + art.artifact_type + T.RESET
                + T.DIM + f"  source={art.source}" + T.RESET
            )
            for ln in wrap_text(art.content, width - 2):
                body.append(f"  {ln}")
            body.append("")
    else:  # transcript
        for msg in adapter.list_messages(session_id):
            label = (
                msg.role if not msg.message_kind
                else f"{msg.role}/{msg.message_kind}"
            )
            color = T.FG_BRIGHT_BLUE if msg.role == "user" else T.FG_BRIGHT_GREEN
            body.append(color + label + T.RESET)
            for ln in wrap_text(msg.content, width - 2):
                body.append(f"  {ln}")
            body.append("")

    viewport_rows = height - HEADER_ROWS - 1   # -1 for scroll indicator line
    max_offset    = max(0, len(body) - viewport_rows)
    scroll_offset = max(0, min(scroll_offset, max_offset))
    visible       = body[scroll_offset : scroll_offset + viewport_rows]

    # Scroll position indicator
    if max_offset > 0:
        pct = int(scroll_offset / max_offset * 100)
        visible.append(T.DIM + f"── {pct}% ({scroll_offset}/{max_offset}) ──" + T.RESET)
    return header + visible


def _approval_queue_lines(selected: int, show_help: bool) -> list[str]:
    adapter   = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width, height = terminal_size()

    lines: list[str] = [
        _header(
            "ORBIT Approval Queue  ·  j/k↑↓ move  ·  Enter inspect  ·  b/Esc back  ·  q exit",
            width,
        ),
        divider(width),
    ]
    if not approvals:
        lines.append(T.DIM + "No pending approvals." + T.RESET)
        return lines

    selected     = min(selected, len(approvals) - 1)
    current      = approvals[selected]
    max_rows     = max(2, min(len(approvals), max(4, height // 3)))

    lines.append(T.BOLD + "Approvals" + T.RESET)
    for i, a in enumerate(approvals[:max_rows]):
        lines.append(_approval_row(a, i == selected, width))
    if len(approvals) > max_rows:
        lines.append(
            T.DIM + f"  … {len(approvals) - max_rows} more approval(s)" + T.RESET
        )
    lines += [
        divider(width),
        T.FG_YELLOW + current.tool_name + T.RESET
        + T.DIM + f"  session={current.session_id}" + T.RESET,
        T.DIM + f"side_effect={current.side_effect_class}" + T.RESET,
        current.summary,
        T.DIM + f"payload={current.payload}" + T.RESET,
    ]
    if show_help:
        lines += [
            divider(width),
            T.BOLD + "Help" + T.RESET,
            "  j / ↓  next approval",
            "  k / ↑  previous approval",
            "  Enter  inspect approval",
            "  b      back to sessions",
            "  q      exit",
        ]
    return lines


def _approval_inspect_lines(approval_idx: int) -> list[str]:
    adapter   = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width, _  = terminal_size()

    if not approvals:
        return [T.DIM + "No pending approvals." + T.RESET]

    approval_idx = min(approval_idx, len(approvals) - 1)
    a = approvals[approval_idx]
    return [
        _header(f"Approval Inspect  ·  {a.tool_name}  ·  any key back", width),
        divider(width),
        T.DIM + f"approval_request_id={a.approval_request_id}" + T.RESET,
        T.DIM + f"session_id={a.session_id}" + T.RESET,
        T.DIM + f"status={a.status}  side_effect={a.side_effect_class}" + T.RESET,
        "",
        a.summary,
        "",
        *wrap_text(str(a.payload), width - 2),
    ]


# ── Inspect sub-loop ──────────────────────────────────────────────────────────

def _run_inspect_session(
    session_id: str,
    tab: str,
    screen: ScreenBuffer,
) -> None:
    """Full-screen inspect loop for a session.  Exits on any non-scroll key."""
    scroll_offset = 0
    screen.invalidate()

    while True:
        width, height = terminal_size()
        screen.render(_inspect_lines(session_id, tab, scroll_offset), width, height)

        raw = read_sequence()
        if not raw:
            debug_log("inspect_session:empty_sequence_return")
            return
        debug_log(f"inspect_session:raw={raw!r}")
        event = parse_sequence(raw)
        debug_log(f"inspect_session:event={event!r}")

        if isinstance(event, ParsedMouse):
            if event.wheel_up:
                scroll_offset = max(0, scroll_offset - 1)
            elif event.wheel_down:
                scroll_offset += 1
            continue

        if isinstance(event, ParsedKey):
            name = event.name
            if name in ("up", "k"):
                scroll_offset = max(0, scroll_offset - 1)
                continue
            if name in ("down", "j"):
                scroll_offset += 1
                continue
            if name == "pageup":
                scroll_offset = max(0, scroll_offset - max(1, height - 6))
                continue
            if name == "pagedown":
                scroll_offset += max(1, height - 6)
                continue

        # Escape or any other non-scroll key → return to browser
        debug_log(f"inspect_session:return_to_browser key={getattr(event, 'name', None)!r}")
        screen.invalidate()
        return


def _run_inspect_approval(approval_idx: int, screen: ScreenBuffer) -> None:
    """Single-frame approval inspect.  Exits on any key."""
    width, height = terminal_size()
    screen.invalidate()
    screen.render(_approval_inspect_lines(approval_idx), width, height)
    read_sequence()     # wait for any key
    screen.invalidate()


# ── Main browse loop ──────────────────────────────────────────────────────────

def browse() -> None:
    debug_log("browse:start")
    adapter  = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        debug_log("browse:no_sessions")
        sys.stdout.write("No sessions available.\n")
        sys.stdout.flush()
        return

    selected          = 0
    approval_selected = 0
    show_help         = False
    tab_index         = 0
    mode              = "sessions"   # "sessions" | "approvals"
    screen            = ScreenBuffer()
    in_paste          = False

    with raw_mode(), alt_screen(), mouse_tracking(), bracketed_paste(), focus_events():
        while True:
            width, height = terminal_size()
            sessions = adapter.list_sessions()
            selected = min(selected, max(0, len(sessions) - 1))

            if mode == "approvals":
                frame = _approval_queue_lines(
                    selected=approval_selected,
                    show_help=show_help,
                )
            else:
                frame = _browser_lines(
                    selected=selected,
                    tab_index=tab_index,
                    show_help=show_help,
                )
            screen.render(frame, width, height)

            # ── Read next input sequence ──────────────────────────────────
            raw = read_sequence()
            if not raw:
                debug_log("browse:empty_sequence")
                continue
            debug_log(f"browse:raw={raw!r}")

            # ── Bracketed paste accumulation ──────────────────────────────
            if raw == T.PASTE_START:
                in_paste = True
                continue
            if raw == T.PASTE_END:
                in_paste = False
                continue
            if in_paste:
                continue

            event = parse_sequence(raw)
            debug_log(f"browse:event={event!r}")
            if event is None:
                continue

            # ── Focus change: force full redraw ───────────────────────────
            if isinstance(event, ParsedFocus):
                screen.invalidate()
                continue

            # ── Mouse events ──────────────────────────────────────────────
            if isinstance(event, ParsedMouse):
                approvals = adapter.list_open_approvals()
                if event.wheel_up:
                    if mode == "sessions":
                        selected = max(0, selected - 1)
                    else:
                        approval_selected = max(0, approval_selected - 1)
                elif event.wheel_down:
                    if mode == "sessions":
                        selected = min(len(sessions) - 1, selected + 1)
                    else:
                        approval_selected = min(
                            len(approvals) - 1, approval_selected + 1
                        )
                continue

            # ── Keyboard events ───────────────────────────────────────────
            if not isinstance(event, ParsedKey):
                continue

            name = event.name
            ctrl = event.ctrl

            # Global: explicit exit only
            if name in ("q", "Q") or (ctrl and name == "c"):
                debug_log(f"browse:exit_key name={name!r} ctrl={ctrl}")
                screen.invalidate()
                screen.render(
                    [T.DIM + "Exited ORBIT workbench." + T.RESET], width, 1
                )
                return

            # Global: toggle help
            if name == "?":
                show_help = not show_help
                continue

            # ── Approval queue mode ───────────────────────────────────────
            if mode == "approvals":
                approvals = adapter.list_open_approvals()
                approval_selected = min(
                    approval_selected, max(0, len(approvals) - 1)
                )
                if name in ("b", "B", "escape"):
                    debug_log(f"browse:approvals_back key={name!r}")
                    mode = "sessions"
                    screen.invalidate()
                elif name in ("j", "down"):
                    approval_selected = min(len(approvals) - 1, approval_selected + 1)
                elif name in ("k", "up"):
                    approval_selected = max(0, approval_selected - 1)
                elif name == "enter" and approvals:
                    _run_inspect_approval(approval_selected, screen)

            # ── Session browser mode ──────────────────────────────────────
            else:
                if name in ("a", "A"):
                    mode = "approvals"
                    screen.invalidate()
                elif name == "escape":
                    debug_log("browse:escape_ignored_in_sessions")
                    continue
                elif name in ("j", "down"):
                    selected = min(len(sessions) - 1, selected + 1)
                elif name in ("k", "up"):
                    selected = max(0, selected - 1)
                elif name in ("t", "T", "tab") and not event.shift:
                    tab_index = (tab_index + 1) % len(SESSION_TABS)
                elif name == "tab" and event.shift:
                    tab_index = (tab_index - 1) % len(SESSION_TABS)
                elif name == "enter" and sessions:
                    _run_inspect_session(
                        sessions[selected].session_id,
                        SESSION_TABS[tab_index],
                        screen,
                    )
