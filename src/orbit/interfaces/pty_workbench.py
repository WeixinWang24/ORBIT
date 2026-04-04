"""Minimal PTY-style mock workbench for ORBIT interface development.

This version renders explicit fixed-width text frames and writes them in a
single flush per redraw to reduce wrapping drift / misaligned rows in PTY mode.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from termios import TCSADRAIN, tcgetattr, tcsetattr
import tty

from .mock_adapter import MockOrbitInterfaceAdapter

SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]
FORCE_EXIT_KEYS = {"q", "Q", "\x1b", "\x03"}
ANSI_CLEAR = "\033[2J\033[H"
ANSI_RESET = "\033[0m"


def _terminal_size() -> os.terminal_size:
    return shutil.get_terminal_size((100, 32))


def _safe_width() -> int:
    return max(40, _terminal_size().columns)


def _safe_height() -> int:
    return max(16, _terminal_size().lines)


def _fit_text(text: str, width: int) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _divider(width: int) -> str:
    return "-" * width


def _emit_frame(lines: list[str]) -> None:
    width = _safe_width()
    height = _safe_height()
    clipped = [_fit_text(line, width) for line in lines[:height]]
    if len(clipped) < height:
        clipped.extend([""] * (height - len(clipped)))
    payload = ANSI_CLEAR + "\n".join(clipped) + ANSI_RESET
    sys.stdout.write(payload)
    sys.stdout.flush()


@contextmanager
def _raw_mode():
    if not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        tcsetattr(fd, TCSADRAIN, old)


def _read_key() -> str:
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        return ch
    if not os.isatty(sys.stdin.fileno()):
        return ch
    seq = ch
    next1 = sys.stdin.read(1)
    seq += next1
    if next1 == "[":
        next2 = sys.stdin.read(1)
        seq += next2
    return seq


def _tab_preview_lines(adapter: MockOrbitInterfaceAdapter, session_id: str, tab: str, max_lines: int) -> list[str]:
    lines: list[str] = []
    if tab == "events":
        for event in adapter.list_events(session_id)[-max_lines:]:
            lines.append(f"{event.event_type}: {event.payload}")
        return lines
    if tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id)[:max_lines]:
            lines.append(f"{call.tool_name}: {call.status} · {call.summary}")
        return lines
    if tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id)[:max_lines]:
            lines.append(f"{artifact.artifact_type}: {artifact.content}")
        return lines
    for message in adapter.list_messages(session_id)[-max_lines:]:
        label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
        lines.append(f"{label}: {message.content}")
    return lines


def _browser_lines(selected: int, tab_index: int, show_help: bool = False) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    width = _safe_width()
    height = _safe_height()
    if not sessions:
        return ["ORBIT Mock Workbench", "", "No sessions."]
    selected = min(selected, len(sessions) - 1)
    current = sessions[selected]
    approvals = [a for a in adapter.list_open_approvals() if a.session_id == current.session_id]
    tab = SESSION_TABS[tab_index]
    tab_bar = " | ".join(f"[{name}]" if i == tab_index else name for i, name in enumerate(SESSION_TABS))
    max_sessions = max(2, min(len(sessions), max(4, height // 4)))
    preview_lines = max(4, min(10, height - max_sessions - (10 if show_help else 7)))
    lines = [
        _fit_text("ORBIT PTY Mock Workbench · mock-only · q/esc/ctrl+c exit · j/k move · t tab · a approvals · enter inspect · ? help", width),
        _divider(width),
        "Sessions",
    ]
    for i, session in enumerate(sessions[:max_sessions]):
        prefix = ">" if i == selected else " "
        lines.append(f"{prefix} {session.session_id} · {session.status} · {session.backend_name} · {session.model}")
    if len(sessions) > max_sessions:
        lines.append(f"... {len(sessions) - max_sessions} more session(s)")
    lines.extend([
        _divider(width),
        f"Current tab: {tab_bar}",
        f"Session: {current.session_id} · conversation={current.conversation_id}",
        f"messages={current.message_count} · approvals={len(approvals)} · tab={tab}",
        _divider(width),
    ])
    lines.extend(_tab_preview_lines(adapter, current.session_id, tab, preview_lines))
    if approvals and preview_lines >= 5:
        lines.append(_divider(width))
        lines.append("Pending approvals for this session")
        for approval in approvals[: max(1, min(3, preview_lines // 2))]:
            lines.append(f"- {approval.tool_name}: {approval.summary}")
    if show_help:
        lines.extend([
            _divider(width),
            "Help",
            "j / down      next session",
            "k / up        previous session",
            "t / tab       next tab",
            "a             switch to approval queue",
            "enter         open detailed inspect view",
            "q / esc / ^C  exit",
        ])
    return lines


def _inspect_lines(session_id: str, tab: str) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    width = _safe_width()
    height = _safe_height()
    if session is None:
        return ["Session not found."]
    lines = [
        _fit_text(f"Session Inspect · {session.session_id} · tab={tab} · press any key to go back", width),
        _divider(width),
        f"backend={session.backend_name} · model={session.model} · status={session.status}",
        _divider(width),
    ]
    max_lines = max(8, height - 6)
    if tab == "events":
        for event in adapter.list_events(session_id):
            lines.append(event.event_type)
            lines.append(str(event.payload))
            lines.append("")
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            lines.append(call.tool_name)
            lines.append(f"status={call.status} · side_effect_class={call.side_effect_class}")
            lines.append(str(call.payload))
            lines.append("")
    elif tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id):
            lines.append(f"{artifact.artifact_type} · source={artifact.source}")
            lines.append(artifact.content)
            lines.append("")
    else:
        for message in adapter.list_messages(session_id):
            label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
            lines.append(label)
            lines.append(message.content)
            lines.append("")
    return lines[:max_lines]


def _approval_queue_lines(selected: int, show_help: bool = False) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width = _safe_width()
    height = _safe_height()
    lines = [
        _fit_text("ORBIT Approval Queue · mock-only · j/k move · enter inspect · b back · q/esc/ctrl+c exit", width),
        _divider(width),
    ]
    if not approvals:
        lines.append("No pending approvals.")
        return lines
    selected = min(selected, len(approvals) - 1)
    current = approvals[selected]
    max_approvals = max(2, min(len(approvals), max(4, height // 3)))
    lines.append("Approvals")
    for i, approval in enumerate(approvals[:max_approvals]):
        prefix = ">" if i == selected else " "
        lines.append(f"{prefix} {approval.tool_name} · {approval.session_id} · {approval.status}")
    if len(approvals) > max_approvals:
        lines.append(f"... {len(approvals) - max_approvals} more approval(s)")
    lines.extend([
        _divider(width),
        f"{current.tool_name} · session={current.session_id}",
        f"side_effect_class={current.side_effect_class}",
        current.summary,
        f"payload={current.payload}",
    ])
    if show_help:
        lines.extend([
            _divider(width),
            "Help",
            "j / down      next approval",
            "k / up        previous approval",
            "enter         open detailed inspect view",
            "b             back to session browser",
            "q / esc / ^C  exit",
        ])
    return lines


def _approval_inspect_lines(selected: int) -> list[str]:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width = _safe_width()
    if not approvals:
        return ["No pending approvals."]
    selected = min(selected, len(approvals) - 1)
    current = approvals[selected]
    return [
        _fit_text(f"Approval Inspect · {current.tool_name} · press any key to go back", width),
        _divider(width),
        f"approval_request_id={current.approval_request_id}",
        f"session_id={current.session_id}",
        f"status={current.status} · side_effect_class={current.side_effect_class}",
        "",
        current.summary,
        "",
        str(current.payload),
    ]


def browse() -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        sys.stdout.write("No sessions available.\n")
        sys.stdout.flush()
        return
    selected = 0
    approval_selected = 0
    show_help = False
    tab_index = 0
    mode = "sessions"
    with _raw_mode():
        while True:
            sessions = adapter.list_sessions()
            selected = min(selected, max(0, len(sessions) - 1))
            if mode == "approvals":
                _emit_frame(_approval_queue_lines(selected=approval_selected, show_help=show_help))
            else:
                _emit_frame(_browser_lines(selected=selected, tab_index=tab_index, show_help=show_help))
            key = _read_key()
            if key in FORCE_EXIT_KEYS:
                _emit_frame(["Exited ORBIT mock workbench."])
                return
            if key in {"?"}:
                show_help = not show_help
                continue
            if mode == "approvals":
                approvals = adapter.list_open_approvals()
                approval_selected = min(approval_selected, max(0, len(approvals) - 1))
                if key in {"b", "B"}:
                    mode = "sessions"
                    continue
                if key in {"j", "\x1b[B"} and approvals:
                    approval_selected = min(len(approvals) - 1, approval_selected + 1)
                    continue
                if key in {"k", "\x1b[A"} and approvals:
                    approval_selected = max(0, approval_selected - 1)
                    continue
                if key in {"\r", "\n"} and approvals:
                    _emit_frame(_approval_inspect_lines(approval_selected))
                    sys.stdin.read(1)
                    continue
            else:
                if key in {"a", "A"}:
                    mode = "approvals"
                    continue
                if key in {"j", "\x1b[B"}:
                    selected = min(len(sessions) - 1, selected + 1)
                    continue
                if key in {"k", "\x1b[A"}:
                    selected = max(0, selected - 1)
                    continue
                if key in {"t", "T", "\t"}:
                    tab_index = (tab_index + 1) % len(SESSION_TABS)
                    continue
                if key in {"\r", "\n"} and sessions:
                    _emit_frame(_inspect_lines(sessions[selected].session_id, SESSION_TABS[tab_index]))
                    sys.stdin.read(1)
                    continue
