"""Notebook helpers for the official OpenAI Platform hello-world route.

This module is intentionally separate from the OpenAI Codex hosted-provider
route. Keeping both surfaces explicit avoids future confusion between:
- official OpenAI Platform `/v1` style calls
- ChatGPT/Codex hosted-provider calls
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.providers.openai_platform import OpenAIOAuthConfig, OpenAIOAuthExecutionBackend


def build_openai_hello_world_descriptor(user_input: str, workspace_root: Path) -> RunDescriptor:
    """Build a simple run descriptor for the official OpenAI notebook demo."""
    return RunDescriptor(
        session_key="session:notebook-openai-hello-world",
        conversation_id="conversation:notebook-openai-hello-world",
        workspace=WorkspaceDescriptor(cwd=str(workspace_root), writable_roots=[str(workspace_root)]),
        user_input=user_input,
    )


def run_openai_hello_world(*, user_input: str, workspace_root: Path, model: str = "gpt-5", api_base: str = "https://api.openai.com/v1", timeout_seconds: int = 60):
    """Execute the first official OpenAI Platform hello-world path."""
    backend = OpenAIOAuthExecutionBackend(config=OpenAIOAuthConfig(model=model, api_base=api_base, timeout_seconds=timeout_seconds), repo_root=workspace_root)
    descriptor = build_openai_hello_world_descriptor(user_input=user_input, workspace_root=workspace_root)
    plan = backend.plan(descriptor)
    return {"descriptor": descriptor, "plan": plan, "backend_name": backend.backend_name, "model": model, "api_base": api_base}


def openai_hello_world_summary_frame(result: dict) -> pd.DataFrame:
    """Render a compact tabular summary for the official OpenAI notebook demo."""
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
