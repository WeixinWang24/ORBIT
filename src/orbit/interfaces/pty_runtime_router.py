"""Helpers for layering runtime-first chat + slash routing onto the raw PTY shell.

This module is the early semantic control layer for the new runtime-first CLI UI.
It is intentionally separate from rendering so route transitions, session actions,
and composer-submit behavior can keep converging here as the PTY workbench
replaces older CLI entrypoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .adapter_protocol import RuntimeCliAdapter
from .runtime_cli_state import (
    APPROVALS_MODE,
    ATTACH_FAILED_BANNER,
    CREATED_SESSION_BANNER,
    DEFAULT_CHAT_BANNER,
    HELP_MODE,
    INSPECT_ARTIFACTS_TAB,
    INSPECT_DEBUG_TAB,
    INSPECT_EVENTS_TAB,
    INSPECT_MODE,
    INSPECT_TAB_ORDER,
    INSPECT_TOOL_CALLS_TAB,
    INSPECT_TRANSCRIPT_TAB,
    RETURN_TO_CHAT_BANNER,
    RuntimeShellState,
    SESSIONS_MODE,
    STATUS_MODE,
    UNKNOWN_COMMAND_BANNER,
    CHAT_MODE,
)


def current_session_id(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> str:
    sessions = adapter.list_sessions()
    if not sessions:
        session = adapter.create_session()
        state.selected_session = 0
        state.active_session_id = session.session_id
        return session.session_id

    if state.active_session_id is not None:
        for index, session in enumerate(sessions):
            if session.session_id == state.active_session_id:
                state.selected_session = index
                return session.session_id

    state.selected_session = 0
    session_id = sessions[0].session_id
    state.active_session_id = session_id
    return session_id


def activate_chat(state: RuntimeShellState, banner: str = RETURN_TO_CHAT_BANNER) -> None:
    state.mode = CHAT_MODE
    state.banner = banner


def activate_sessions(state: RuntimeShellState) -> None:
    state.mode = SESSIONS_MODE


def activate_approvals(state: RuntimeShellState) -> None:
    state.mode = APPROVALS_MODE


def activate_help(state: RuntimeShellState) -> None:
    state.mode = HELP_MODE


def activate_status(state: RuntimeShellState) -> None:
    state.mode = STATUS_MODE


def activate_inspect(state: RuntimeShellState, tab_index: int) -> None:
    state.mode = INSPECT_MODE
    state.tab_index = tab_index


def cycle_inspect_tab(state: RuntimeShellState, *, reverse: bool = False) -> None:
    current_index = INSPECT_TAB_ORDER.index(state.tab_index)
    delta = -1 if reverse else 1
    state.tab_index = INSPECT_TAB_ORDER[(current_index + delta) % len(INSPECT_TAB_ORDER)]


def hop_inspect_session(state: RuntimeShellState, adapter: RuntimeCliAdapter, *, reverse: bool = False) -> None:
    sessions = adapter.list_sessions()
    if not sessions:
        return
    delta = -1 if reverse else 1
    state.selected_session = max(0, min(len(sessions) - 1, state.selected_session + delta))
    state.active_session_id = sessions[state.selected_session].session_id


def attach_current_session(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    state.active_session_id = session_id
    activate_chat(state, f"Attached to {session_id}")


def attach_named_session(state: RuntimeShellState, adapter: RuntimeCliAdapter, session_id: str, *, failure_kind: str = "attach_error") -> None:
    current_id = current_session_id(state, adapter)
    target = adapter.attach_session(session_id)
    if target is None:
        adapter.append_system_message(current_id, f"Session not found: {session_id}", kind=failure_kind)
        activate_chat(state, ATTACH_FAILED_BANNER)
        return
    sessions = adapter.list_sessions()
    state.selected_session = next(i for i, s in enumerate(sessions) if s.session_id == target.session_id)
    state.active_session_id = target.session_id
    activate_chat(state, f"Attached to {target.session_id}")


def show_pending_approval(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    pending = adapter.get_pending_approval(session_id)
    if pending is None:
        adapter.append_system_message(session_id, "No pending approval for this session.", kind="pending_info")
        activate_chat(state, "No pending approval")
        return
    summary = (
        f"Pending approval: {pending.tool_name} "
        f"(approval_request_id={pending.approval_request_id}, side_effect={pending.side_effect_class})"
    )
    adapter.append_system_message(session_id, summary, kind="pending_approval")
    activate_chat(state, "Pending approval loaded")


def show_current_session_messages(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    messages = adapter.list_messages(session_id)
    if not messages:
        adapter.append_system_message(session_id, "No messages yet.", kind="show_info")
        activate_chat(state, "No messages yet")
        return
    activate_chat(state, f"Loaded transcript for {session_id}")


def show_current_session_state(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    payload = adapter.get_session_state_payload(session_id)
    if payload is None:
        adapter.append_system_message(session_id, "Session not found.", kind="state_error")
        activate_chat(state, "Session not found")
        return
    adapter.append_system_message(session_id, str(payload), kind="session_state")
    activate_chat(state, "Session state loaded")


def run_self_audit_entrypoint(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    payload = adapter.get_workbench_status()
    runtime_mode = str(payload.get("runtime_mode") or "dev")
    if runtime_mode != "evo":
        adapter.append_system_message(
            session_id,
            "Self-audit entrypoint is not enabled in the current mode. Re-run in evo mode to perform implementation-grounded self-audit work.",
            kind="self_audit_blocked",
        )
        activate_chat(state, "Self-audit requires evo mode")
        return
    workspace_root = Path(str(payload.get('workspace_root') or '.'))
    key_paths = [
        'src/orbit/runtime/core/session_manager.py',
        'src/orbit/runtime/core/contracts.py',
        'src/orbit/runtime/governance/protocol/mode.py',
        'src/orbit/interfaces/runtime_adapter.py',
    ]

    grounding_records: list[dict[str, object]] = []

    def _file_grounding_line(rel_path: str) -> list[str]:
        target = workspace_root / rel_path
        if not target.exists() or not target.is_file():
            grounding_records.append({"path": rel_path, "exists": False})
            return [f"    - {rel_path}: exists=False"]
        stat = target.stat()
        try:
            content = target.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            grounding_records.append({
                "path": rel_path,
                "exists": True,
                "bytes": stat.st_size,
                "text_decode": "utf8_failed",
            })
            return [f"    - {rel_path}: exists=True bytes={stat.st_size} text_decode=utf8_failed"]
        lines = content.splitlines()
        header = " | ".join(line.strip() for line in lines[:3] if line.strip())
        header = header[:160] if header else "(no non-empty header lines)"
        grounding_records.append({
            "path": rel_path,
            "exists": True,
            "bytes": stat.st_size,
            "lines": len(lines),
            "header": header,
        })
        return [
            f"    - {rel_path}: exists=True bytes={stat.st_size} lines={len(lines)}",
            f"      header={header}",
        ]
    report_lines = [
        "SELF-AUDIT BOOTSTRAP REPORT",
        "",
        "runtime:",
        f"  runtime_mode={payload.get('runtime_mode')}",
        f"  workspace_root={payload.get('workspace_root')}",
        f"  mode_policy_profile={payload.get('mode_policy_profile')}",
        f"  self_runtime_visibility={payload.get('self_runtime_visibility')}",
        f"  self_modification_posture={payload.get('self_modification_posture')}",
        "",
        "inventory:",
        f"  registered_tool_count={payload.get('registered_tool_count')}",
        f"  session_count={payload.get('session_count')}",
        f"  approval_count={payload.get('approval_count')}",
        f"  native_list_available_tools_present={'native__list_available_tools' in set(payload.get('registered_tool_names', []))}",
        "",
        "build_state:",
        f"  active_build_id={payload.get('active_build_id')}",
        f"  candidate_build_id={payload.get('candidate_build_id')}",
        f"  last_known_good_build_id={payload.get('last_known_good_build_id')}",
        "",
        "first_evidence_collection:",
        "  key_runtime_paths:",
    ]
    for rel_path in key_paths:
        report_lines.extend(_file_grounding_line(rel_path))
    checklist_entries = [
        "runtime/registry evidence collected",
        "implementation-path evidence collected",
        "design-intent evidence separated from runtime truth",
        "derived observations labeled as derived",
        "self-change remains read-heavy unless separately approved",
    ]
    report_lines += [
        "",
        "phase_a_evidence_checklist:",
        "  - runtime/registry evidence collected",
        "  - implementation-path evidence collected",
        "  - design-intent evidence separated from runtime truth",
        "  - derived observations labeled as derived",
        "  - self-change remains read-heavy unless separately approved",
        "",
        "recommended_next_step:",
        "  - use this report as the bootstrap state before implementation-grounded self-audit work",
    ]
    structured_payload = {
        "artifact_type": "self_audit_bootstrap",
        "schema_version": "v1",
        "phase": "phase_a",
        "report_kind": "self_audit_bootstrap",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "runtime_mode": payload.get("runtime_mode"),
            "workspace_root": payload.get("workspace_root"),
            "mode_policy_profile": payload.get("mode_policy_profile"),
            "self_runtime_visibility": payload.get("self_runtime_visibility"),
            "self_modification_posture": payload.get("self_modification_posture"),
        },
        "inventory": {
            "registered_tool_count": payload.get("registered_tool_count"),
            "session_count": payload.get("session_count"),
            "approval_count": payload.get("approval_count"),
            "native_list_available_tools_present": "native__list_available_tools" in set(payload.get("registered_tool_names", [])),
        },
        "build_state": {
            "active_build_id": payload.get("active_build_id"),
            "candidate_build_id": payload.get("candidate_build_id"),
            "last_known_good_build_id": payload.get("last_known_good_build_id"),
        },
        "first_evidence_collection": {
            "source_paths": key_paths,
            "key_runtime_paths": grounding_records,
        },
        "phase_a_evidence_checklist": checklist_entries,
        "recommended_next_step": "use this report as the bootstrap state before implementation-grounded self-audit work",
    }
    structured_json = json.dumps(structured_payload, indent=2, ensure_ascii=False)
    message_text = "\n".join(report_lines) + "\n\nSTRUCTURED_PAYLOAD_JSON\n" + structured_json
    adapter.append_system_message(session_id, message_text, kind="self_audit_report")
    adapter.append_context_artifact(
        session_id,
        artifact_type="self_audit_bootstrap",
        content=structured_json,
        source="self_audit_entrypoint",
    )
    activate_chat(state, "Self-audit bootstrap ready")


def detach_current_session(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    sessions = adapter.list_sessions()
    if not sessions:
        session = adapter.create_session()
        state.selected_session = 0
        state.active_session_id = session.session_id
        activate_chat(state, f"Detached to new session {session.session_id}")
        return
    state.selected_session = 0
    state.active_session_id = sessions[0].session_id
    activate_chat(state, f"Detached to {sessions[0].session_id}")


def clear_current_session(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    session_id = current_session_id(state, adapter)
    ok = adapter.clear_session(session_id)
    if not ok:
        adapter.append_system_message(session_id, "Current store does not support session deletion.", kind="clear_error")
        activate_chat(state, "Clear failed")
        return
    sessions = adapter.list_sessions()
    if not sessions:
        session = adapter.create_session()
        state.selected_session = 0
        state.active_session_id = session.session_id
        activate_chat(state, f"Deleted session {session_id}; new session {session.session_id} ready")
        return
    state.selected_session = 0
    state.active_session_id = sessions[0].session_id
    activate_chat(state, f"Deleted session {session_id}")


def clear_all_runtime_sessions(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    ok = adapter.clear_all_sessions()
    if not ok:
        session_id = current_session_id(state, adapter)
        adapter.append_system_message(session_id, "Current store does not support clearing all sessions.", kind="clear_error")
        activate_chat(state, "Clear-all failed")
        return
    session = adapter.create_session()
    state.selected_session = 0
    state.active_session_id = session.session_id
    activate_chat(state, f"Deleted all sessions; new session {session.session_id} ready")


def wipe_runtime_session_history(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    ok = adapter.wipe_session_history()
    if not ok:
        session_id = current_session_id(state, adapter)
        adapter.append_system_message(session_id, "Current store does not support wiping session history.", kind="clear_error")
        activate_chat(state, "Wipe-history failed")
        return
    session = adapter.create_session()
    state.selected_session = 0
    state.active_session_id = session.session_id
    activate_chat(state, f"Wiped ORBIT session history; new session {session.session_id} ready")


def resolve_current_approval(state: RuntimeShellState, adapter: RuntimeCliAdapter, decision: str, note: str | None = None) -> None:
    session_id = current_session_id(state, adapter)
    before = adapter.get_pending_approval(session_id)
    result = adapter.resolve_pending_approval(session_id, decision, note)
    if result is None:
        adapter.append_system_message(session_id, "No pending approval for this session.", kind="approval_info")
        activate_chat(state, "No pending approval")
        return
    after = adapter.get_pending_approval(session_id)
    final_text = getattr(result, "final_text", None)
    plan_label = getattr(result, "plan_label", None)
    if after is None:
        outcome = f"Approval {decision}d and no pending approval remains."
    elif before is not None and after.approval_request_id != before.approval_request_id:
        outcome = (
            f"Approval {decision}d for {before.approval_request_id}, but the resumed run opened a new pending approval "
            f"{after.approval_request_id} for {after.tool_name}."
        )
    else:
        outcome = (
            f"Approval {decision}d, but pending approval still appears open "
            f"({after.approval_request_id if after is not None else 'unknown'})."
        )
    if final_text or plan_label:
        adapter.append_system_message(
            session_id,
            (final_text or plan_label or f"Approval {decision}d.") + "\n\n" + outcome,
            kind="approval_result",
        )
    else:
        adapter.append_system_message(session_id, outcome, kind="approval_result")
    activate_chat(state, f"Approval {decision}d")


def resolve_current_approval_via_picker(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> tuple[str, str | None, str | None] | None:
    session_id = current_session_id(state, adapter)
    pending = adapter.get_pending_approval(session_id)
    if pending is None:
        activate_chat(state, "No pending approval")
        return None

    index = getattr(state, "approval_picker_index", 0)
    if index <= 0:
        return ("approve", None, None)
    if index == 1:
        return (
            "approve",
            pending.tool_name,
            "approved similar tool path for this session via chat approval picker",
        )
    return ("reject", None, None)


def route_slash_command(state: RuntimeShellState, adapter: RuntimeCliAdapter, text: str) -> None:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command in {"/help", "/h"}:
        activate_help(state)
        return
    if command == "/chat":
        activate_chat(state)
        return
    if command in {"/i", "/inspect"}:
        activate_inspect(state, INSPECT_TRANSCRIPT_TAB)
        return
    if command == "/events":
        activate_inspect(state, INSPECT_EVENTS_TAB)
        return
    if command == "/tools":
        activate_inspect(state, INSPECT_TOOL_CALLS_TAB)
        return
    if command == "/artifacts":
        activate_inspect(state, INSPECT_ARTIFACTS_TAB)
        return
    if command in {"/debug", "/debug-log", "/debuglog"}:
        activate_inspect(state, INSPECT_DEBUG_TAB)
        return
    if command == "/approvals":
        activate_approvals(state)
        return
    if command == "/status":
        activate_status(state)
        return
    if command == "/self-audit":
        run_self_audit_entrypoint(state, adapter)
        return
    if command == "/sessions":
        activate_sessions(state)
        return
    if command == "/new":
        session = adapter.create_session()
        state.selected_session = 0
        state.active_session_id = session.session_id
        activate_chat(state, CREATED_SESSION_BANNER)
        return
    if command == "/attach":
        attach_named_session(state, adapter, arg, failure_kind="attach_error")
        return
    if command == "/detach":
        detach_current_session(state, adapter)
        return
    if command == "/show":
        show_current_session_messages(state, adapter)
        return
    if command == "/state":
        show_current_session_state(state, adapter)
        return
    if command == "/clear":
        clear_current_session(state, adapter)
        return
    if command == "/clear-all":
        clear_all_runtime_sessions(state, adapter)
        return
    if command == "/wipe-history":
        wipe_runtime_session_history(state, adapter)
        return
    if command == "/pending":
        show_pending_approval(state, adapter)
        return
    if command == "/approve":
        resolve_current_approval(state, adapter, "approve", arg or None)
        return
    if command == "/reject":
        resolve_current_approval(state, adapter, "reject", arg or None)
        return

    session_id = current_session_id(state, adapter)
    adapter.append_system_message(session_id, f"Unknown slash command: {text}", kind="slash_error")
    activate_chat(state, UNKNOWN_COMMAND_BANNER)


def submit_composer(state: RuntimeShellState, adapter: RuntimeCliAdapter) -> None:
    text = state.composer.text.strip()
    if not text:
        state.banner = "Composer is empty"
        return
    session_id = current_session_id(state, adapter)
    pending = adapter.get_pending_approval(session_id)
    if pending is not None and not text.startswith("/"):
        activate_approvals(state)
        state.composer.text = ""
        state.banner = (
            f"Pending approval for {pending.tool_name}. Use /approve or /reject, "
            "or press a/r in the approvals panel."
        )
        return
    if text.startswith("/"):
        route_slash_command(state, adapter, text)
        state.composer.text = ""
        return
    state.pending_submit_session_id = session_id
    state.pending_submit_text = text
    state.runtime_busy = True
    state.completed_submit_banner = None
    state.completed_submit_error = None
    activate_chat(state, f"Running turn for {session_id}...")
    state.composer.text = ""
