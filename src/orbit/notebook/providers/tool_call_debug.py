"""Notebook helpers for inspecting the first tool-call detection/closure path."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from orbit.models import ConversationMessage, MessageRole
from orbit.notebook.display.dataframes import session_messages_dataframe
from orbit.runtime import SessionManager
from orbit.runtime.execution.continuation_context import build_rejection_continuation_context
from orbit.runtime.providers.openai_codex import OpenAICodexConfig, OpenAICodexExecutionBackend
from orbit.runtime.providers.ssh_vllm import SshVllmConfig, SshVllmExecutionBackend
from orbit.runtime.transports.openai_codex_http import post_and_read_sse_events
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
    store = create_default_store()
    session_manager = SessionManager(store=store, backend=backend, workspace_root=str(workspace_root))
    session = session_manager.create_session(backend_name='ssh-vllm', model=backend.config.model)
    final_plan = session_manager.run_session_turn(session_id=session.session_id, user_input=prompt)
    inspect = {
        'session': session_manager.get_session(session.session_id),
        'messages': session_manager.list_messages(session.session_id),
    }
    return {"session_manager": session_manager, "session": session, "final_plan": final_plan, "inspect": inspect}



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



def run_tool_call_approval_demo(*, workspace_root: Path, backend: SshVllmExecutionBackend, prompt: str, decision: str = 'approve', note: str | None = None) -> dict:
    """Run a first approval-gated session turn and optionally resolve it.

    This helper is intentionally linear:
    1. create session
    2. submit a prompt that should produce an approval-gated tool request
    3. inspect pending approvals
    4. approve or reject one waiting request
    5. inspect final transcript state
    """
    store = create_default_store()
    session_manager = SessionManager(store=store, backend=backend, workspace_root=str(workspace_root))
    session = session_manager.create_session(backend_name='ssh-vllm', model=backend.config.model)
    waiting_plan = session_manager.run_session_turn(session_id=session.session_id, user_input=prompt)
    open_approvals = session_manager.list_open_session_approvals()
    session_approval = next((item for item in open_approvals if item['session_id'] == session.session_id), None)
    resolved_plan = None
    if session_approval is not None:
        resolved_plan = session_manager.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval['approval_request_id'],
            decision=decision,
            note=note,
        )
    inspect = {
        'session': session_manager.get_session(session.session_id),
        'messages': session_manager.list_messages(session.session_id),
    }
    messages_df = session_messages_dataframe(store, session.session_id)
    return {
        'session_manager': session_manager,
        'session': session,
        'waiting_plan': waiting_plan,
        'open_approvals': open_approvals,
        'session_approval': session_approval,
        'resolved_plan': resolved_plan,
        'inspect': inspect,
        'messages_df': messages_df,
    }



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
            'last_message_role': str(messages[-1].role) if messages else None,
            'last_message_kind': messages[-1].metadata.get('message_kind') if messages else None,
        }
    ])



def probe_codex_tool_call_raw_events(*, workspace_root: Path, prompt: str, model: str = 'gpt-5.4') -> dict:
    """Capture raw SSE events for a Codex hosted tool-call probe.

    This helper is intentionally low-level so notebooks can inspect:
    - request payload
    - raw SSE events
    - normalized ORBIT interpretation
    """
    backend = OpenAICodexExecutionBackend(
        config=OpenAICodexConfig(model=model),
        repo_root=workspace_root,
    )
    messages = [
        ConversationMessage(
            session_id='session:codex-raw-probe',
            role=MessageRole.USER,
            content=prompt,
            turn_index=1,
        )
    ]
    credential = backend.load_persisted_credential()
    auth = backend.resolve_auth_material(credential)
    payload = backend.build_request_payload_from_messages(messages, session=None)
    events = post_and_read_sse_events(
        url=backend.build_request_url(),
        headers=backend.build_request_headers(auth),
        payload=payload,
        timeout_seconds=backend.config.timeout_seconds,
    )
    normalized = backend.normalize_events(events)
    return {
        'backend': backend,
        'payload': payload,
        'events': events,
        'normalized_plan': normalized,
    }



def codex_raw_events_frame(result: dict) -> pd.DataFrame:
    rows = []
    for index, event in enumerate(result['events']):
        payload = event.payload if isinstance(event.payload, dict) else {}
        rows.append(
            {
                'index': index,
                'type': payload.get('type'),
                'raw_line': event.raw_line,
                'payload_json': json.dumps(payload, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows)



def probe_rejection_continuation_context(messages: list[ConversationMessage]) -> dict:
    """Build the current rejection continuation package for inspection."""
    package = build_rejection_continuation_context(messages)
    return {
        'messages': messages,
        'package': package,
    }



def continuation_context_summary_frame(result: dict) -> pd.DataFrame:
    package = result.get('package')
    if package is None:
        return pd.DataFrame([
            {
                'context_kind': None,
                'has_bridge_message': False,
                'has_system_prompt': False,
                'allowed_next_actions_count': 0,
                'tool_name': None,
            }
        ])
    return pd.DataFrame([
        {
            'context_kind': package.context_kind,
            'has_bridge_message': package.bridge_message is not None,
            'has_system_prompt': bool(package.system_prompt),
            'allowed_next_actions_count': len(package.allowed_next_actions),
            'tool_name': package.metadata.get('tool_name'),
        }
    ])



def continuation_context_payload(result: dict) -> dict:
    package = result.get('package')
    if package is None:
        return {'package': None}
    return package.model_dump(mode='json')



def tool_call_approval_summary_frame(result: dict) -> pd.DataFrame:
    """Summarize the first approval-gated session demo in one row."""
    waiting_plan = result['waiting_plan']
    resolved_plan = result.get('resolved_plan')
    session_approval = result.get('session_approval')
    messages = result['inspect']['messages']
    return pd.DataFrame([
        {
            'session_id': result['session'].session_id,
            'waiting_plan_label': waiting_plan.plan_label,
            'waiting_tool_name': waiting_plan.tool_request.tool_name if waiting_plan.tool_request else None,
            'approval_request_id': session_approval.get('approval_request_id') if session_approval else None,
            'resolved_plan_label': resolved_plan.plan_label if resolved_plan else None,
            'resolved_final_text': resolved_plan.final_text if resolved_plan else None,
            'message_count': len(messages),
            'last_message_role': str(messages[-1].role) if messages else None,
            'last_message_kind': messages[-1].metadata.get('message_kind') if messages else None,
        }
    ])
