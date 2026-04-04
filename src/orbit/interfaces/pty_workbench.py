"""Minimal PTY-style mock workbench for ORBIT interface development.

This is intentionally lightweight and runtime-disconnected.
It provides a keyboard-loop session browser over the mock adapter so the PTY
interaction grammar can be validated before real adapter integration.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from termios import TCSADRAIN, tcgetattr, tcsetattr
import tty

from rich.console import Console

from .mock_adapter import MockOrbitInterfaceAdapter

console = Console()
SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]


def _clear() -> None:
    console.print("\033[2J\033[H", end="")


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


def _render_tab_preview(adapter: MockOrbitInterfaceAdapter, session_id: str, tab: str) -> None:
    if tab == "events":
        for event in adapter.list_events(session_id)[-5:]:
            console.print(f"[magenta]{event.event_type}[/magenta]: {event.payload}")
        return
    if tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            console.print(f"[magenta]{call.tool_name}[/magenta]: {call.status} · {call.summary}")
        return
    if tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id):
            console.print(f"[magenta]{artifact.artifact_type}[/magenta]: {artifact.content}")
        return
    for message in adapter.list_messages(session_id)[-3:]:
        label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
        console.print(f"[magenta]{label}[/magenta]: {message.content}")


def _render_browser(selected: int, tab_index: int, show_help: bool = False) -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        _clear()
        console.print("ORBIT Mock Workbench\n\nNo sessions.")
        return
    current = sessions[selected]
    approvals = [a for a in adapter.list_open_approvals() if a.session_id == current.session_id]
    tab = SESSION_TABS[tab_index]
    tab_bar = "  ".join(f"[bold cyan]{name}[/bold cyan]" if i == tab_index else f"[dim]{name}[/dim]" for i, name in enumerate(SESSION_TABS))
    _clear()
    console.print("[bold magenta]ORBIT PTY Mock Workbench[/bold magenta]  [cyan]mock-only[/cyan]  [dim]q/esc exit · j/k move · t tab · a approvals · enter inspect · ? help[/dim]\n")
    console.print("[bold]Sessions[/bold]")
    for i, session in enumerate(sessions):
        prefix = "➜" if i == selected else " "
        style = "bold cyan" if i == selected else "white"
        console.print(f"[{style}]{prefix} {session.session_id}[/] [dim]{session.status} · {session.backend_name} · {session.model}[/]")
    console.print(f"\n[bold]Current tab[/bold]  {tab_bar}")
    console.print("\n[bold]Preview[/bold]")
    console.print(f"[cyan]{current.session_id}[/cyan] [dim]conversation={current.conversation_id}[/dim]")
    console.print(f"[dim]messages={current.message_count} · approvals={len(approvals)} · tab={tab}[/dim]\n")
    _render_tab_preview(adapter, current.session_id, tab)
    if approvals:
        console.print("\n[yellow]Pending approvals for this session[/yellow]")
        for approval in approvals:
            console.print(f"- {approval.tool_name}: {approval.summary}")
    if show_help:
        console.print("\n[bold]Help[/bold]")
        console.print("j / ↓    next session")
        console.print("k / ↑    previous session")
        console.print("t        next tab")
        console.print("a        switch to approval queue")
        console.print("enter    open detailed inspect view")
        console.print("?        toggle help")
        console.print("q / esc  exit")


def _render_inspect(session_id: str, tab: str) -> None:
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    if session is None:
        return
    _clear()
    console.print(f"[bold magenta]Session Inspect[/bold magenta] [cyan]{session.session_id}[/cyan] [dim]tab={tab} · press any key to go back[/dim]\n")
    console.print(f"backend={session.backend_name} · model={session.model} · status={session.status}\n")
    if tab == "events":
        for event in adapter.list_events(session_id):
            console.print(f"[magenta]{event.event_type}[/magenta]")
            console.print(event.payload)
            console.print()
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(session_id):
            console.print(f"[magenta]{call.tool_name}[/magenta]")
            console.print(f"status={call.status} · side_effect_class={call.side_effect_class}")
            console.print(call.payload)
            console.print()
    elif tab == "artifacts":
        for artifact in adapter.list_artifacts(session_id):
            console.print(f"[magenta]{artifact.artifact_type}[/magenta] [dim]source={artifact.source}[/dim]")
            console.print(artifact.content)
            console.print()
    else:
        for message in adapter.list_messages(session_id):
            label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
            console.print(f"[magenta]{label}[/magenta]")
            console.print(message.content)
            console.print()
    sys.stdin.read(1)


def _render_approval_queue(selected: int, show_help: bool = False) -> None:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    _clear()
    console.print("[bold magenta]ORBIT Approval Queue[/bold magenta]  [cyan]mock-only[/cyan]  [dim]j/k move · enter inspect · b back · q/esc exit[/dim]\n")
    if not approvals:
        console.print("No pending approvals.")
        return
    current = approvals[selected]
    console.print("[bold]Approvals[/bold]")
    for i, approval in enumerate(approvals):
        prefix = "➜" if i == selected else " "
        style = "bold yellow" if i == selected else "white"
        console.print(f"[{style}]{prefix} {approval.tool_name}[/] [dim]{approval.session_id} · {approval.status}[/dim]")
    console.print("\n[bold]Preview[/bold]")
    console.print(f"[yellow]{current.tool_name}[/yellow] [dim]session={current.session_id}[/dim]")
    console.print(f"[dim]side_effect_class={current.side_effect_class}[/dim]")
    console.print(current.summary)
    console.print(f"payload={current.payload}")
    if show_help:
        console.print("\n[bold]Help[/bold]")
        console.print("j / ↓    next approval")
        console.print("k / ↑    previous approval")
        console.print("enter    open detailed inspect view")
        console.print("b        back to session browser")
        console.print("?        toggle help")
        console.print("q / esc  exit")


def _render_approval_inspect(selected: int) -> None:
    adapter = MockOrbitInterfaceAdapter()
    approvals = adapter.list_open_approvals()
    if not approvals:
        return
    current = approvals[selected]
    _clear()
    console.print(f"[bold magenta]Approval Inspect[/bold magenta] [yellow]{current.tool_name}[/yellow] [dim]press any key to go back[/dim]\n")
    console.print(f"approval_request_id={current.approval_request_id}")
    console.print(f"session_id={current.session_id}")
    console.print(f"status={current.status} · side_effect_class={current.side_effect_class}\n")
    console.print(current.summary)
    console.print()
    console.print(current.payload)
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
            if mode == "approvals":
                _render_approval_queue(selected=approval_selected, show_help=show_help)
            else:
                _render_browser(selected=selected, tab_index=tab_index, show_help=show_help)
            key = _read_key()
            if key in {"q", "Q", "\x1b"}:
                _clear()
                console.print("Exited ORBIT mock workbench.")
                return
            if key in {"?"}:
                show_help = not show_help
                continue
            if mode == "approvals":
                approvals = adapter.list_open_approvals()
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
                if key in {"\r", "\n"}:
                    _render_inspect(sessions[selected].session_id, SESSION_TABS[tab_index])
                    continue
