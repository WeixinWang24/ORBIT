"""Notebook helpers for inspecting the first tool-call detection/closure path."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.models import ConversationMessage, MessageRole
from orbit.runtime import OrbitCoordinator
from orbit.runtime.providers.ssh_vllm import SshVllmConfig, SshVllmExecutionBackend
from orbit.runtime.transports.ssh_tunnel import SshTunnelConfig
from orbit.runtime.transports.ssh_vllm_http import ensure_ssh_vllm_endpoint
from orbit.store import create_default_store



def build_tool_call_probe_backend(*, workspace_root: Path, remote_base_url: str, model: str, api_key: str = "EMPTY", auto_tunnel: bool = False, ssh_host: str = "", local_port: int = 8000, remote_host: str = "127.0.0.1", remote_port: int = 8000) -> SshVllmExecutionBackend:
    return SshVllmExecutionBackend(
        config=SshVllmConfig(
            remote_base_url=remote_base_url,
            model=model,
            api_key=api_key,
            auto_tunnel=auto_tunnel,
            ssh_host=ssh_host,
            local_port=local_port,
            remote_host=remote_host,
            remote_port=remote_port,
            workspace_root=str(workspace_root),
        )
    )



def resolve_probe_base_url(*, backend: SshVllmExecutionBackend) -> str:
    headers = backend.build_request_headers()
    tunnel_config = None
    if backend.config.auto_tunnel:
        tunnel_config = SshTunnelConfig(
            ssh_host=backend.config.ssh_host,
            local_port=backend.config.local_port,
            remote_host=backend.config.remote_host,
            remote_port=backend.config.remote_port,
        )
    return ensure_ssh_vllm_endpoint(
        base_url=backend.config.remote_base_url,
        headers=headers,
        auto_tunnel=backend.config.auto_tunnel,
        tunnel_config=tunnel_config,
    )



def probe_tool_call_request(*, backend: SshVllmExecutionBackend, prompt: str) -> dict:
    messages = [ConversationMessage(session_id='session:tool-probe', role=MessageRole.USER, content=prompt, turn_index=1)]
    payload = backend.build_request_payload_from_messages(messages)
    plan = backend.plan_from_messages(messages, session=None)
    ready_base_url = resolve_probe_base_url(backend=backend)
    return {"payload": payload, "plan": plan, "ready_base_url": ready_base_url}



def run_tool_call_closure(*, workspace_root: Path, backend: SshVllmExecutionBackend, prompt: str) -> dict:
    coordinator = OrbitCoordinator(store=create_default_store(), workspace_root=workspace_root, backend=backend)
    session = coordinator.create_session(backend_name='ssh-vllm', model=backend.config.model)
    final_plan = coordinator.run_session_turn(session_id=session.session_id, user_input=prompt)
    inspect = coordinator.inspect_session(session.session_id)
    return {"coordinator": coordinator, "session": session, "final_plan": final_plan, "inspect": inspect}



def tool_call_probe_summary_frame(result: dict) -> pd.DataFrame:
    plan = result['plan']
    return pd.DataFrame([
        {
            'ready_base_url': result.get('ready_base_url'),
            'plan_label': plan.plan_label,
            'source_backend': plan.source_backend,
            'has_tool_request': plan.tool_request is not None,
            'tool_name': plan.tool_request.tool_name if plan.tool_request else None,
            'requires_approval': plan.tool_request.requires_approval if plan.tool_request else None,
            'side_effect_class': plan.tool_request.side_effect_class if plan.tool_request else None,
            'failure_reason': plan.failure_reason,
        }
    ])



def tool_call_closure_summary_frame(result: dict) -> pd.DataFrame:
    plan = result['final_plan']
    messages = result['inspect']['messages']
    return pd.DataFrame([
        {
            'session_id': result['session'].session_id,
            'plan_label': plan.plan_label,
            'source_backend': plan.source_backend,
            'final_text': plan.final_text,
            'message_count': len(messages),
            'last_message_role': messages[-1].role if messages else None,
            'last_message_kind': messages[-1].metadata.get('message_kind') if messages else None,
        }
    ])
