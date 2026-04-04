"""Mock-driven CLI workbench for isolated ORBIT interface development.

CLI direction here borrows from coding-agent / operational CLIs with grouped
subcommands and inspect-oriented verbs, while remaining runtime-disconnected.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .mock_adapter import MockOrbitInterfaceAdapter

app = typer.Typer(help="ORBIT mock interface CLI")
session_app = typer.Typer(help="Inspect mock sessions")
approval_app = typer.Typer(help="Inspect mock approvals")
workbench_app = typer.Typer(help="PTY-oriented mock workbench commands")
app.add_typer(session_app, name="session")
app.add_typer(approval_app, name="approval")
app.add_typer(workbench_app, name="workbench")
console = Console()


def _adapter() -> MockOrbitInterfaceAdapter:
    return MockOrbitInterfaceAdapter()


@session_app.command("list")
def session_list() -> None:
    """List mock sessions for interface development."""
    adapter = _adapter()
    table = Table(title="ORBIT Mock Sessions")
    table.add_column("session_id")
    table.add_column("status")
    table.add_column("backend")
    table.add_column("model")
    table.add_column("messages")
    table.add_column("last_message")
    for session in adapter.list_sessions():
        table.add_row(
            session.session_id,
            session.status,
            session.backend_name,
            session.model,
            str(session.message_count),
            session.last_message_preview,
        )
    console.print(table)


@session_app.command("show")
def session_show(session_id: str) -> None:
    """Show mock transcript for one session."""
    adapter = _adapter()
    session = adapter.get_session(session_id)
    if session is None:
        console.print(f"[red]Session not found:[/red] {session_id}")
        raise typer.Exit(code=1)
    console.print(Panel.fit(f"backend={session.backend_name}\nmodel={session.model}\nstatus={session.status}", title=session.session_id))
    for message in adapter.list_messages(session_id):
        label = message.role if not message.message_kind else f"{message.role} ({message.message_kind})"
        console.print(Panel(message.content, title=label, expand=False))


@session_app.command("events")
def session_events(session_id: str) -> None:
    """Show mock runtime events for one session."""
    adapter = _adapter()
    console.print_json(json.dumps([event.model_dump(mode="json") for event in adapter.list_events(session_id)], indent=2, ensure_ascii=False))


@session_app.command("tool-calls")
def session_tool_calls(session_id: str) -> None:
    """Show mock tool calls for one session."""
    adapter = _adapter()
    console.print_json(json.dumps([call.model_dump(mode="json") for call in adapter.list_tool_calls(session_id)], indent=2, ensure_ascii=False))


@approval_app.command("list")
def approval_list() -> None:
    """Show open mock approvals."""
    adapter = _adapter()
    console.print_json(json.dumps([approval.model_dump(mode="json") for approval in adapter.list_open_approvals()], indent=2, ensure_ascii=False))


@workbench_app.command("plan")
def workbench_plan() -> None:
    """Show the current PTY workbench interaction plan."""
    console.print(Panel.fit(
        "mode=session-browser\nlayout=list + preview + side-summary\nkeys=j/k enter tab shift-tab / ? esc q\nstatus=mock-only, runtime-disconnected",
        title="ORBIT PTY Workbench Plan",
    ))


@app.command("overview")
def overview() -> None:
    """Show a compact overview of the mock workbench state."""
    adapter = _adapter()
    sessions = adapter.list_sessions()
    approvals = adapter.list_open_approvals()
    console.print(Panel.fit(
        f"sessions={len(sessions)}\napprovals={len(approvals)}\nactive_like={sum(1 for s in sessions if s.status == 'active')}",
        title="ORBIT Mock Overview",
    ))


if __name__ == "__main__":
    app()
