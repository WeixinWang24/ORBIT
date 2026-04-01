"""Notebook helpers for the SSH vLLM comparison demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.providers.ssh_vllm import SshVllmConfig, SshVllmExecutionBackend



def build_ssh_vllm_hello_world_descriptor(user_input: str, workspace_root: Path) -> RunDescriptor:
    """Build a simple run descriptor for the SSH vLLM notebook demo."""
    return RunDescriptor(
        session_key="session:notebook-ssh-vllm-hello-world",
        conversation_id="conversation:notebook-ssh-vllm-hello-world",
        workspace=WorkspaceDescriptor(cwd=str(workspace_root), writable_roots=[str(workspace_root)]),
        user_input=user_input,
    )



def run_ssh_vllm_hello_world(
    *,
    user_input: str,
    workspace_root: Path,
    remote_base_url: str,
    model: str,
    api_key: str = "EMPTY",
    timeout_seconds: int = 60,
    auto_tunnel: bool = False,
    ssh_host: str = "",
    local_port: int = 8000,
    remote_host: str = "127.0.0.1",
    remote_port: int = 8000,
):
    """Execute the first SSH vLLM comparison hello-world path."""
    backend = SshVllmExecutionBackend(
        config=SshVllmConfig(
            remote_base_url=remote_base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            auto_tunnel=auto_tunnel,
            ssh_host=ssh_host,
            local_port=local_port,
            remote_host=remote_host,
            remote_port=remote_port,
        )
    )
    descriptor = build_ssh_vllm_hello_world_descriptor(user_input=user_input, workspace_root=workspace_root)
    plan = backend.plan(descriptor)
    return {
        "descriptor": descriptor,
        "plan": plan,
        "backend_name": backend.backend_name,
        "model": model,
        "remote_base_url": remote_base_url,
        "auto_tunnel": auto_tunnel,
        "ssh_host": ssh_host,
    }



def ssh_vllm_hello_world_summary_frame(result: dict) -> pd.DataFrame:
    """Render a compact tabular summary for the SSH vLLM demo."""
    plan = result["plan"]
    return pd.DataFrame(
        [
            {
                "backend": result["backend_name"],
                "model": result["model"],
                "remote_base_url": result["remote_base_url"],
                "auto_tunnel": result["auto_tunnel"],
                "ssh_host": result["ssh_host"],
                "plan_label": plan.plan_label,
                "source_backend": plan.source_backend,
                "has_final_text": bool(plan.final_text),
                "final_text": plan.final_text,
                "has_tool_request": plan.tool_request is not None,
                "failure_reason": plan.failure_reason,
            }
        ]
    )
