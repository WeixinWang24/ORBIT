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
import termios
import tty

from rich.console import Console

from .mock_adapter import MockOrbitInterfaceAdapter

console = Console()


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


def _render_browser(selected: int, show_help: bool = False) -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        _clear()
        console.print("ORBIT Mock Workbench\n\nNo sessions.")
        return
    current = sessions[selected]
    messages = adapter.list_messages(current.session_id)
    approvals = [a for a in adapter.list_open_approvals() if a.session_id == current.session_id]
    _clear()
    console.print("[bold magenta]ORBIT PTY Mock Workbench[/bold magenta]  [cyan]mock-only[/cyan]  [dim]q/esc exit · j/k move · enter inspect · ? help[/dim]\n")
    console.print("[bold]Sessions[/bold]")
    for i, session in enumerate(sessions):
        prefix = "➜" if i == selected else " "
        style = "bold cyan" if i == selected else "white"
        console.print(f"[{style}]{prefix} {session.session_id}[/] [dim]{session.status} · {session.backend_name} · {session.model}[/]")
    console.print("\n[bold]Preview[/bold]")
    console.print(f"[cyan]{current.session_id}[/cyan] [dim]conversation={current.conversation_id}[/dim]")
    console.print(f"[dim]messages={current.message_count} · approvals={len(approvals)}[/dim]\n")
    for message in messages[-3:]:
        label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
        console.print(f"[magenta]{label}[/magenta]: {message.content}")
    if approvals:
        console.print("\n[yellow]Pending approvals[/yellow]")
        for approval in approvals:
            console.print(f"- {approval.tool_name}: {approval.summary}")
    if show_help:
        console.print("\n[bold]Help[/bold]")
        console.print("j / ↓    next session")
        console.print("k / ↑    previous session")
        console.print("enter    open detailed inspect view")
        console.print("?        toggle help")
        console.print("q / esc  exit")


def _render_inspect(session_id: str) -> None:
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    if session is None:
        return
    _clear()
    console.print(f"[bold magenta]Session Inspect[/bold magenta] [cyan]{session.session_id}[/cyan] [dim](press any key to go back)[/dim]\n")
    console.print(f"backend={session.backend_name} · model={session.model} · status={session.status}\n")
    for message in adapter.list_messages(session_id):
        label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
        console.print(f"[magenta]{label}[/magenta]")
        console.print(message.content)
        console.print()
    sys.stdin.read(1)


def browse() -> None:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    if not sessions:
        console.print("No sessions available.")
        return
    selected = 0
    show_help = False
    with _raw_mode():
        while True:
            _render_browser(selected=selected, show_help=show_help)
            key = _read_key()
            if key in {"q", "Q", "\x1b"}:
                _clear()
                console.print("Exited ORBIT mock workbench.")
                return
            if key in {"?"}:
                show_help = not show_help
                continue
            if key in {"j", "\x1b[B"}:
                selected = min(len(sessions) - 1, selected + 1)
                continue
            if key in {"k", "\x1b[A"}:
                selected = max(0, selected - 1)
                continue
            if key in {"\r", "\n"}:
                _render_inspect(sessions[selected].session_id)
                continue
