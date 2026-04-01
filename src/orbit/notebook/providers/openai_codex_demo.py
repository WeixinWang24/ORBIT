"""Notebook helpers for the first OpenAI Codex hello-world demonstration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.providers.openai_codex import OPENAI_CODEX_BASE_URL, OpenAICodexConfig, OpenAICodexExecutionBackend


def build_openai_codex_hello_world_descriptor(user_input: str, workspace_root: Path) -> RunDescriptor:
    """Build a simple run descriptor for the first notebook-based Codex demo."""
    return RunDescriptor(
        session_key="session:notebook-openai-codex-hello-world",
        conversation_id="conversation:notebook-openai-codex-hello-world",
        workspace=WorkspaceDescriptor(cwd=str(workspace_root), writable_roots=[str(workspace_root)]),
        user_input=user_input,
    )


def run_openai_codex_hello_world(*, user_input: str, workspace_root: Path, model: str = "gpt-5.4", api_base: str = OPENAI_CODEX_BASE_URL, timeout_seconds: int = 60):
    """Execute the first OpenAI Codex hosted-provider hello-world path."""
    backend = OpenAICodexExecutionBackend(config=OpenAICodexConfig(model=model, api_base=api_base, timeout_seconds=timeout_seconds), repo_root=workspace_root)
    descriptor = build_openai_codex_hello_world_descriptor(user_input=user_input, workspace_root=workspace_root)
    plan = backend.plan(descriptor)
    return {"descriptor": descriptor, "plan": plan, "backend_name": backend.backend_name, "model": model, "api_base": api_base}


def openai_codex_hello_world_summary_frame(result: dict) -> pd.DataFrame:
    """Render a compact tabular summary for the Codex notebook demo."""
    plan = result["plan"]
    return pd.DataFrame([
        {
            "backend": result["backend_name"],
            "model": result["model"],
            "api_base": result["api_base"],
            "plan_label": plan.plan_label,
            "source_backend": plan.source_backend,
            "has_final_text": bool(plan.final_text),
            "final_text": plan.final_text,
            "has_tool_request": plan.tool_request is not None,
            "failure_reason": plan.failure_reason,
        }
    ])
