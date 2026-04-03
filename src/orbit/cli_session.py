from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from orbit.runtime import SessionManager
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.runtime.providers.openai_codex import OpenAICodexConfig, OpenAICodexExecutionBackend
from orbit.settings import DEFAULT_WORKSPACE_ROOT, REPO_ROOT
from orbit.store import create_default_store

app = typer.Typer(help="ORBIT SessionManager-mainline session chat CLI")
chat_app = typer.Typer(help="Session chat commands")
app.add_typer(chat_app, name="chat")
console = Console()


def _build_codex_session_manager(*, model: str, enable_tools: bool = False, enable_mcp_filesystem: bool = False) -> SessionManager:
    backend = OpenAICodexExecutionBackend(
        config=OpenAICodexConfig(model=model, enable_tools=enable_tools),
        repo_root=REPO_ROOT,
        workspace_root=DEFAULT_WORKSPACE_ROOT,
    )
    return SessionManager(
        store=create_default_store(),
        backend=backend,
        workspace_root=str(DEFAULT_WORKSPACE_ROOT),
        enable_mcp_filesystem=enable_mcp_filesystem,
    )


def _role_name(role) -> str:
    return getattr(role, "value", str(role))


def _print_messages(session_manager: SessionManager, session_id: str) -> None:
    messages = session_manager.list_messages(session_id)
    if not messages:
        console.print("[dim]No messages yet.[/dim]")
        return
    for index, message in enumerate(messages, start=1):
        kind = message.metadata.get("message_kind") if isinstance(message.metadata, dict) else None
        role = _role_name(message.role)
        title = f"{index}. {role}"
        if kind:
            title += f" ({kind})"
        console.print(Panel(message.content, title=title, expand=False))


def _print_state(session_manager: SessionManager, session_id: str) -> None:
    session = session_manager.get_session(session_id)
    if session is None:
        console.print("[red]Session not found.[/red]")
        return
    console.print_json(json.dumps(session.model_dump(mode="json"), indent=2, ensure_ascii=False))


def _print_events(session_manager: SessionManager, session_id: str) -> None:
    session = session_manager.get_session(session_id)
    if session is None:
        console.print("[red]Session not found.[/red]")
        return
    events = session_manager.store.list_events_for_run(session.conversation_id)
    if not events:
        console.print("[dim]No runtime events yet.[/dim]")
        return
    rows = []
    for event in events:
        rows.append(
            {
                "event_type": getattr(event.event_type, "value", str(event.event_type)),
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
            }
        )
    console.print_json(json.dumps(rows, indent=2, ensure_ascii=False))


def _print_sessions(session_manager: SessionManager, *, current_session_id: str | None) -> None:
    sessions = session_manager.store.list_sessions()
    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return
    table = Table(title="Stored ORBIT Sessions")
    table.add_column("current")
    table.add_column("session_id")
    table.add_column("updated_at")
    table.add_column("messages")
    table.add_column("last_message")
    for session in sessions:
        messages = session_manager.list_messages(session.session_id)
        last_message = messages[-1].content if messages else ""
        if len(last_message) > 60:
            last_message = last_message[:57] + "..."
        table.add_row(
            "*" if session.session_id == current_session_id else "",
            session.session_id,
            session.updated_at.isoformat(),
            str(len(messages)),
            last_message,
        )
    console.print(table)


def _create_session(session_manager: SessionManager, *, model: str):
    session = session_manager.create_session(backend_name="openai-codex", model=model)
    console.print(Panel.fit(f"session_id: {session.session_id}\nconversation_id: {session.conversation_id}", title="New ORBIT Session"))
    return session


def _print_help() -> None:
    console.print("[dim]Session scope commands:[/dim] /show /state /events /clear /detach")
    console.print("[dim]Runtime scope commands:[/dim] /sessions /attach <session_id> /new /clear-all /help /exit")


def _clear_session(session_manager: SessionManager, session_id: str) -> None:
    delete_fn = getattr(session_manager.store, "delete_session", None)
    if not callable(delete_fn):
        console.print(Panel("Current store does not support session deletion.", title="Clear Error", border_style="red", expand=False))
        return
    delete_fn(session_id)
    console.print(Panel.fit(f"Deleted session: {session_id}", title="Session Cleared"))


def _clear_all_sessions(session_manager: SessionManager) -> None:
    delete_all_fn = getattr(session_manager.store, "delete_all_sessions", None)
    if not callable(delete_all_fn):
        console.print(Panel("Current store does not support clearing all sessions.", title="Clear Error", border_style="red", expand=False))
        return
    delete_all_fn()
    console.print(Panel.fit("Deleted all stored sessions.", title="All Sessions Cleared"))


def _load_or_create_session(session_manager: SessionManager, *, model: str, session_id: str | None):
    if session_id:
        session = session_manager.get_session(session_id)
        if session is None:
            console.print(Panel(f"Session not found: {session_id}", title="Resume Error", border_style="red", expand=False))
            raise typer.Exit(code=1)
        console.print(Panel.fit(f"session_id: {session.session_id}\nconversation_id: {session.conversation_id}", title="Resumed ORBIT Session"))
        return session
    return _create_session(session_manager, model=model)


@chat_app.callback(invoke_without_command=True)
def chat(
    model: str = typer.Option("gpt-5.4", help="Codex model id."),
    session_id: str | None = typer.Option(None, "--session-id", help="Resume an existing session by session id."),
    enable_tools: bool = typer.Option(False, "--enable-tools", help="Enable local tool definitions for governed tool-calling tests."),
    enable_mcp_filesystem: bool = typer.Option(False, "--enable-mcp-filesystem", help="Enable the local filesystem MCP server and register its tools."),
) -> None:
    """Run a minimal SessionManager-mainline chat REPL."""
    session_manager = _build_codex_session_manager(
        model=model,
        enable_tools=enable_tools,
        enable_mcp_filesystem=enable_mcp_filesystem,
    )
    session = _load_or_create_session(session_manager, model=model, session_id=session_id)

    current_session = session
    _print_help()
    while True:
        prompt_label = current_session.session_id if current_session is not None else "orbit-session"
        try:
            user_input = typer.prompt(prompt_label, prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting session chat.[/dim]")
            raise typer.Exit()

        command = user_input.strip()
        if not command:
            continue
        if command == "/exit":
            console.print("[dim]Bye.[/dim]")
            raise typer.Exit()
        if command == "/help":
            _print_help()
            continue
        if command == "/sessions":
            _print_sessions(session_manager, current_session_id=current_session.session_id if current_session else None)
            continue
        if command.startswith("/attach "):
            target_session_id = command.split(maxsplit=1)[1].strip()
            target_session = session_manager.get_session(target_session_id)
            if target_session is None:
                console.print(Panel(f"Session not found: {target_session_id}", title="Attach Error", border_style="red", expand=False))
                continue
            current_session = target_session
            console.print(Panel.fit(f"session_id: {current_session.session_id}\nconversation_id: {current_session.conversation_id}", title="Attached ORBIT Session"))
            continue
        if command == "/detach":
            if current_session is None:
                console.print("[dim]Already detached.[/dim]")
            else:
                console.print(Panel.fit(f"Detached from session: {current_session.session_id}", title="Detached"))
                current_session = None
            continue
        if command == "/new":
            current_session = _create_session(session_manager, model=model)
            continue
        if command == "/clear":
            if current_session is None:
                console.print("[dim]/clear is a session-scope command. Attach a session first, or use /clear-all from runtime scope.[/dim]")
                continue
            target = current_session.session_id
            current_session = None
            _clear_session(session_manager, target)
            continue
        if command == "/clear-all":
            if current_session is not None:
                console.print("[dim]/clear-all is a runtime-scope destructive command. Use /detach first, then run /clear-all.[/dim]")
                continue
            _clear_all_sessions(session_manager)
            continue
        if command == "/show":
            if current_session is None:
                console.print("[dim]No session attached. Use /new or /attach <session_id>.[/dim]")
                continue
            _print_messages(session_manager, current_session.session_id)
            continue
        if command == "/state":
            if current_session is None:
                console.print("[dim]No session attached. Use /new or /attach <session_id>.[/dim]")
                continue
            _print_state(session_manager, current_session.session_id)
            continue
        if command == "/events":
            if current_session is None:
                console.print("[dim]No session attached. Use /new or /attach <session_id>.[/dim]")
                continue
            _print_events(session_manager, current_session.session_id)
            continue
        if current_session is None:
            console.print("[dim]No session attached. Use /new or /attach <session_id> before sending messages.[/dim]")
            continue

        try:
            plan = session_manager.run_session_turn(session_id=current_session.session_id, user_input=user_input)
        except OpenAIAuthStoreError as exc:
            console.print(Panel(
                f"OpenAI credential error: {exc}\n\nTip: bootstrap or restore the repo-local OpenAI OAuth credential store before using this chat surface.",
                title="Auth Error",
                border_style="red",
                expand=False,
            ))
            continue
        except Exception as exc:
            console.print(Panel(str(exc), title="Session Chat Error", border_style="red", expand=False))
            continue

        messages = session_manager.list_messages(current_session.session_id)
        assistant_message: Optional[str] = None
        for message in reversed(messages):
            if _role_name(message.role) == "assistant":
                assistant_message = message.content
                break
        if assistant_message:
            console.print(Panel(assistant_message, title="assistant", expand=False))
        elif plan.final_text:
            console.print(Panel(plan.final_text, title="assistant", expand=False))
        else:
            console.print("[yellow]No assistant final text returned for this turn.[/yellow]")


if __name__ == "__main__":
    app()
