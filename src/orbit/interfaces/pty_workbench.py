"""Minimal PTY-style mock workbench for ORBIT interface development.

This is intentionally lightweight and runtime-disconnected.
It provides a keyboard-loop session browser over the mock adapter so the PTY
interaction grammar can be validated before real adapter integration.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from termios import TCSADRAIN, tcgetattr, tcsetattr
import tty

from rich.console import Console

from .mock_adapter import MockOrbitInterfaceAdapter

console = Console()
SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]
FORCE_EXIT_KEYS = {"q", "Q", "\x1b", "\x03"}


def _clear() -> None:
    console.print("\033[2J\033[H", end="")


def _terminal_size() -> os.terminal_size:
    return shutil.get_terminal_size((100, 32))


def _fit_text(text: str, width: int) -> str:
    if width <= 4:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _divider() -> str:
    cols = _terminal_size().columns
    return "─" * max(12, min(cols - 2, 120))


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


def _render_tab_preview(adapter: MockOrbitInterfaceAdapter, session_id: str, tab: str, width: int, max_lines: int) -> None:
    lines_printed = 0

    def emit(line: str) -> None:
        nonlocal lines_printed
        if lines_printed >= max_lines:
            return
        console.print(_fit_text(line, width))
        lines_printed += 1

    if tab == "events":
        for event in adapter.list_events(session_id)[-max_lines:]:
            emit(f"[magenta]{event.event_type}[/magenta]: {event.payload}")
        return
    if tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id)[:max_lines]:
            emit(f"[magenta]{call.tool_name}[/magenta]: {call.status} · {call.summary}")
        return
    if tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id)[:max_lines]:
            emit(f"[magenta]{artifact.artifact_type}[/magenta]: {artifact.content}")
        return
    for message in adapter.list_messages(session_id)[-max_lines:]:
        label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
        emit(f"[magenta]{label}[/magenta]: {message.content}")


def _render_browser(selected: int, tab_index: int, show_help: bool = False) -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    width = _terminal_size().columns
    height = _terminal_size().lines
    if not sessions:
        _clear()
        console.print("ORBIT Mock Workbench\n\nNo sessions.")
        return
    current = sessions[selected]
    approvals = [a for a in adapter.list_open_approvals() if a.session_id == current.session_id]
    tab = SESSION_TABS[tab_index]
    tab_bar = "  ".join(f"[bold cyan]{name}[/bold cyan]" if i == tab_index else f"[dim]{name}[/dim]" for i, name in enumerate(SESSION_TABS))
    max_sessions = max(2, min(len(sessions), max(4, height // 4)))
    preview_lines = max(4, min(10, height - max_sessions - (10 if show_help else 7)))
    _clear()
    console.print(_fit_text("[bold magenta]ORBIT PTY Mock Workbench[/bold magenta]  [cyan]mock-only[/cyan]  [dim]q/esc/ctrl+c exit · j/k move · t tab · a approvals · enter inspect · ? help[/dim]", width))
    console.print(_divider())
    console.print("[bold]Sessions[/bold]")
    visible_sessions = sessions[:max_sessions]
    for i, session in enumerate(visible_sessions):
        prefix = "➜" if i == selected else " "
        style = "bold cyan" if i == selected else "white"
        line = f"{prefix} {session.session_id} {session.status} · {session.backend_name} · {session.model}"
        console.print(f"[{style}]{_fit_text(line, width)}[/]")
    if selected >= len(visible_sessions):
        console.print(f"[dim]… {len(sessions) - len(visible_sessions)} more session(s)[/dim]")
    console.print(_divider())
    console.print(_fit_text(f"[bold]Current tab[/bold]  {tab_bar}", width))
    console.print(_fit_text(f"[cyan]{current.session_id}[/cyan] [dim]conversation={current.conversation_id}[/dim]", width))
    console.print(_fit_text(f"[dim]messages={current.message_count} · approvals={len(approvals)} · tab={tab}[/dim]", width))
    console.print(_divider())
    _render_tab_preview(adapter, current.session_id, tab, width=width, max_lines=preview_lines)
    if approvals and preview_lines >= 5:
        console.print(_divider())
        console.print("[yellow]Pending approvals for this session[/yellow]")
        for approval in approvals[: max(1, min(3, preview_lines // 2))]:
            console.print(_fit_text(f"- {approval.tool_name}: {approval.summary}", width))
    if show_help:
        console.print(_divider())
        console.print("[bold]Help[/bold]")
        for line in [
            "j / ↓    next session",
            "k / ↑    previous session",
            "t / tab  next tab",
            "a        switch to approval queue",
            "enter    open detailed inspect view",
            "?        toggle help",
            "q / esc / ctrl+c  exit",
        ]:
            console.print(_fit_text(line, width))


def _render_inspect(session_id: str, tab: str) -> None:
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    width = _terminal_size().columns
    height = _terminal_size().lines
    if session is None:
        return
    _clear()
    console.print(_fit_text(f"[bold magenta]Session Inspect[/bold magenta] [cyan]{session.session_id}[/cyan] [dim]tab={tab} · press any key to go back[/dim]", width))
    console.print(_divider())
    console.print(_fit_text(f"backend={session.backend_name} · model={session.model} · status={session.status}", width))
    console.print(_divider())
    max_lines = max(8, height - 6)
    lines_printed = 0

    def emit(line: str) -> None:
        nonlocal lines_printed
        if lines_printed >= max_lines:
            return
        console.print(_fit_text(line, width))
        lines_printed += 1

    if tab == "events":
        for event in adapter.list_events(session_id):
            emit(f"{event.event_type}")
            emit(str(event.payload))
            emit("")
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            emit(call.tool_name)
            emit(f"status={call.status} · side_effect_class={call.side_effect_class}")
            emit(str(call.payload))
            emit("")
    elif tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id):
            emit(f"{artifact.artifact_type} · source={artifact.source}")
            emit(artifact.content)
            emit("")
    else:
        for message in adapter.list_messages(session_id):
            label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
            emit(label)
            emit(message.content)
            emit("")
    sys.stdin.read(1)


def _render_approval_queue(selected: int, show_help: bool = False) -> None:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width = _terminal_size().columns
    height = _terminal_size().lines
    _clear()
    console.print(_fit_text("[bold magenta]ORBIT Approval Queue[/bold magenta]  [cyan]mock-only[/cyan]  [dim]j/k move · enter inspect · b back · q/esc/ctrl+c exit[/dim]", width))
    console.print(_divider())
    if not approvals:
        console.print("No pending approvals.")
        return
    current = approvals[selected]
    max_approvals = max(2, min(len(approvals), max(4, height // 3)))
    console.print("[bold]Approvals[/bold]")
    for i, approval in enumerate(approvals[:max_approvals]):
        prefix = "➜" if i == selected else " "
        style = "bold yellow" if i == selected else "white"
        line = f"{prefix} {approval.tool_name} {approval.session_id} · {approval.status}"
        console.print(f"[{style}]{_fit_text(line, width)}[/]")
    if selected >= max_approvals:
        console.print(f"[dim]… {len(approvals) - max_approvals} more approval(s)[/dim]")
    console.print(_divider())
    console.print(_fit_text(f"[yellow]{current.tool_name}[/yellow] [dim]session={current.session_id}[/dim]", width))
    console.print(_fit_text(f"[dim]side_effect_class={current.side_effect_class}[/dim]", width))
    console.print(_fit_text(current.summary, width))
    console.print(_fit_text(f"payload={current.payload}", width))
    if show_help:
        console.print(_divider())
        for line in [
            "j / ↓    next approval",
            "k / ↑    previous approval",
            "enter    open detailed inspect view",
            "b        back to session browser",
            "?        toggle help",
            "q / esc / ctrl+c  exit",
        ]:
            console.print(_fit_text(line, width))


def _render_approval_inspect(selected: int) -> None:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    width = _terminal_size().columns
    if not approvals:
        return
    current = approvals[selected]
    _clear()
    console.print(_fit_text(f"[bold magenta]Approval Inspect[/bold magenta] [yellow]{current.tool_name}[/yellow] [dim]press any key to go back[/dim]", width))
    console.print(_divider())
    for line in [
        f"approval_request_id={current.approval_request_id}",
        f"session_id={current.session_id}",
        f"status={current.status} · side_effect_class={current.side_effect_class}",
        "",
        current.summary,
        "",
        str(current.payload),
    ]:
        console.print(_fit_text(line, width))
    sys.stdin.read(1)


def browse() -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        console.print("No sessions available.")
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
                _render_approval_queue(selected=approval_selected, show_help=show_help)
            else:
                _render_browser(selected=selected, tab_index=tab_index, show_help=show_help)
            key = _read_key()
            if key in FORCE_EXIT_KEYS:
                _clear()
                console.print("Exited ORBIT mock workbench.")
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
                    _render_approval_inspect(approval_selected)
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
                    _render_inspect(sessions[selected].session_id, SESSION_TABS[tab_index])
                    continue
