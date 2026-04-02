"""CLI entrypoints for the current ORBIT scaffold.

Current posture:
- this CLI still reflects the older `OrbitCoordinator`-centric scaffold surface
- it is retained mainly for legacy bring-up, historical reference, and teaching
- Jupyter Notebook remains the primary workbench surface
- the active runtime mainline now centers on `SessionManager`, not this CLI

This file should therefore be treated as a legacy scaffold-facing CLI until a
separate SessionManager-mainline CLI surface is designed intentionally.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from orbit.notebook import project_run
from orbit.runtime.historical import OrbitCoordinator
from orbit.runtime.providers.openai_platform import OpenAIOAuthExecutionBackend
from orbit.settings import DEFAULT_WORKSPACE_ROOT
from orbit.store import create_default_store

app = typer.Typer(help="ORBIT legacy scaffold / teaching CLI (active runtime mainline is SessionManager-centered)")
console = Console()


@app.command()
def demo(dummy_scenario: str = "tool_then_finish") -> None:
    """Run the legacy dummy-driven ORBIT scaffold and print the result."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    result = coordinator.run(user_input="Demo request", dummy_scenario=dummy_scenario)
    console.print_json(json.dumps(result.model_dump(), indent=2))


@app.command()
def approvals() -> None:
    """Print pending approvals from the legacy scaffold path in a readable table."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    records = coordinator.list_pending_approvals()
    table = Table(title="Pending ORBIT approvals")
    table.add_column("run_id")
    table.add_column("approval_id")
    table.add_column("tool_name")
    table.add_column("arguments")
    for record in records:
        table.add_row(record.run_id, record.approval_id, record.tool_name, json.dumps(record.arguments))
    console.print(table)


@app.command()
def approvals_json() -> None:
    """Print pending approvals as JSON from the legacy scaffold path."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    console.print_json(json.dumps([r.model_dump() for r in coordinator.list_pending_approvals()], indent=2))


@app.command()
def approve(approval_id: str) -> None:
    """Approve a pending tool request by approval id through the legacy scaffold path."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    result = coordinator.approve(approval_id)
    console.print_json(json.dumps(result.model_dump(), indent=2))


@app.command()
def reject(approval_id: str) -> None:
    """Reject a pending tool request by approval id through the legacy scaffold path."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    result = coordinator.reject(approval_id)
    console.print_json(json.dumps(result.model_dump(), indent=2))


@app.command()
def inspect(run_id: str) -> None:
    """Print a readable inspection view for a stored run from the legacy scaffold path."""
    console.print(project_run(run_id=run_id, store=create_default_store()))


@app.command()
def inspect_json(run_id: str) -> None:
    """Print a stored run as JSON from the legacy scaffold path."""
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=DEFAULT_WORKSPACE_ROOT)
    result = coordinator.inspect(run_id)
    console.print_json(json.dumps(result.model_dump(), indent=2))


@app.command("oauth-url")
def oauth_url(originator: str = "pi") -> None:
    """Generate and print the OpenAI OAuth login URL bundle."""
    backend = OpenAIOAuthExecutionBackend(repo_root=DEFAULT_WORKSPACE_ROOT)
    session = backend.create_pkce_handshake_session(originator=originator)
    console.print_json(json.dumps({
        "authorize_url": session.authorize_url,
        "state": session.state,
        "code_verifier": session.code_verifier,
        "code_challenge": session.code_challenge,
        "redirect_uri": session.redirect_uri,
        "originator": session.originator,
    }, indent=2))


if __name__ == "__main__":
    app()
