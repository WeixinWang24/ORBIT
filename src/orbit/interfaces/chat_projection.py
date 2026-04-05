"""Chat projection helpers for the runtime-first ORBIT PTY CLI.

First slice:
- centralize projection of current session transcript into renderable lines
- keep transcript projection separate from fixed shell/header status
- leave an obvious extension point for future assistant delta / inflight rendering
"""

from __future__ import annotations

from dataclasses import dataclass

from . import termio as T
from .composer_state import wrap_display_text


@dataclass
class ChatProjection:
    lines: list[str]
    session_id: str
    has_busy_banner: bool = False
    assistant_inflight_text: str | None = None


def build_chat_projection(*, adapter, session_id: str, width: int, runtime_busy: bool, pending_submit_session_id: str | None, pending_submit_text: str, submit_started_at: float | None, assistant_inflight_text: str | None, accent_user: str, accent_assistant: str, accent_warning: str, accent_muted: str, approval_picker_index: int = 0, approval_action_pending: bool = False, approval_action_label: str | None = None) -> ChatProjection:
    lines: list[str] = []
    body: list[str] = []
    hidden_kinds = {
        "approval_request",
        "approval_guidance",
        "structured_reauthorization",
        "approval_decision",
    }
    for msg in adapter.list_messages(session_id):
        if msg.message_kind in hidden_kinds:
            continue
        label = msg.role.upper() if not msg.message_kind else f"{msg.role.upper()} [{msg.message_kind}]"
        color = accent_user if msg.role == "user" else accent_assistant if msg.role == "assistant" else accent_warning
        if msg.message_kind == "tool_result":
            tool_name = None
            tool_ok = None
            if isinstance(msg.metadata, dict):
                tool_name = msg.metadata.get("tool_name")
                tool_ok = msg.metadata.get("tool_ok")
            summary = f"TOOL [tool_result] tool={tool_name or 'unknown'}"
            if tool_ok is True:
                summary += " status=ok"
            elif tool_ok is False:
                summary += " status=error"
            compact = summary.replace("\n", " ")
            max_width = max(20, width)
            if len(compact) > max_width:
                compact = compact[: max(0, max_width - 1)] + "…"
            body.append(T.DIM + compact + T.RESET)
            body.append("")
            continue
        body.append(color + label + T.RESET)
        wrapped = wrap_display_text(msg.content, max(20, width - 4))
        for ln in wrapped:
            body.append("  " + ln)
        body.append("")

    pending = adapter.get_pending_approval(session_id)
    if pending is not None:
        options = [
            "approve once",
            "approve similar for this session",
            "deny",
        ]
        selected_index = max(0, min(approval_picker_index, len(options) - 1))
        body.append(accent_warning + "ASSISTANT [approval_picker]" + T.RESET)
        body.extend("  " + ln for ln in wrap_display_text(
            f"Approval required for {pending.tool_name} (side_effect_class={pending.side_effect_class}).",
            max(20, width - 4),
        ))
        if approval_action_pending and approval_action_label:
            body.extend("  " + ln for ln in wrap_display_text(approval_action_label, max(20, width - 4)))
        else:
            body.extend("  " + ln for ln in wrap_display_text(
                "Use ↑/↓ to choose and Enter to confirm.",
                max(20, width - 4),
            ))
            body.extend("  " + ln for ln in wrap_display_text(
                "‘approve similar for this session’ grants structured reauthorization for this tool in the current session.",
                max(20, width - 4),
            ))
        for idx, option in enumerate(options):
            prefix = "▶ " if idx == selected_index else "  "
            line = prefix + option
            if idx == selected_index:
                body.append("  " + accent_warning + T.INVERSE + line + T.RESET)
            else:
                body.append("  " + accent_muted + line + T.RESET)
        body.append("")

    if assistant_inflight_text:
        body.append(accent_assistant + "ASSISTANT [streaming]" + T.RESET)
        wrapped = wrap_display_text(assistant_inflight_text, max(20, width - 4))
        for ln in wrapped:
            body.append("  " + ln)
        body.append("")

    if not body:
        body.append(accent_muted + T.DIM + "No messages yet. Start typing below." + T.RESET)

    lines.extend(body)
    return ChatProjection(lines=lines, session_id=session_id, has_busy_banner=runtime_busy, assistant_inflight_text=assistant_inflight_text)
