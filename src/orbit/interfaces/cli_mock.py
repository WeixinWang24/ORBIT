"""Mock-driven CLI workbench for isolated ORBIT interface development."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .mock_adapter import MockOrbitInterfaceAdapter

app = typer.Typer(help="ORBIT mock interface CLI")
console = Console()


@app.command("sessions")
def sessions() -> None:
    """List mock sessions for interface development."""
    adapter = MockOrbitInterfaceAdapter()
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


@app.command("show")
def show(session_id: str) -> None:
    """Show mock transcript for one session."""
    adapter = MockOrbitInterfaceAdapter()
    session = adapter.get_session(session_id)
    if session is None:
        console.print(f"[red]Session not found:[/red] {session_id}")
        raise typer.Exit(code=1)
    console.print(Panel.fit(f"backend={session.backend_name}\nmodel={session.model}\nstatus={session.status}", title=session.session_id))
    for message in adapter.list_messages(session_id):
        label = message.role if not message.message_kind else f"{message.role} ({message.message_kind})"
        console.print(Panel(message.content, title=label, expand=False))


@app.command("events")
def events(session_id: str) -> None:
    """Show mock runtime events for one session."""
    adapter = MockOrbitInterfaceAdapter()
    console.print_json(json.dumps([event.model_dump(mode="json") for event in adapter.list_events(session_id)], indent=2, ensure_ascii=False))


@app.command("tool-calls")
def tool_calls(session_id: str) -> None:
    """Show mock tool calls for one session."""
    adapter = MockOrbitInterfaceAdapter()
    console.print_json(json.dumps([call.model_dump(mode="json") for call in adapter.list_tool_calls(session_id)], indent=2, ensure_ascii=False))


@app.command("approvals")
def approvals() -> None:
    """Show open mock approvals."""
    adapter = MockOrbitInterfaceAdapter()
    console.print_json(json.dumps([approval.model_dump(mode="json") for approval in adapter.list_open_approvals()], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
