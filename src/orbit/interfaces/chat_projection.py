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


def build_chat_projection(*, adapter, session_id: str, width: int, runtime_busy: bool, pending_submit_session_id: str | None, pending_submit_text: str, submit_started_at: float | None, assistant_inflight_text: str | None, accent_user: str, accent_assistant: str, accent_warning: str, accent_muted: str) -> ChatProjection:
    lines: list[str] = []
    body: list[str] = []
    for msg in adapter.list_messages(session_id):
        label = msg.role.upper() if not msg.message_kind else f"{msg.role.upper()} [{msg.message_kind}]"
        color = accent_user if msg.role == "user" else accent_assistant if msg.role == "assistant" else accent_warning
        body.append(color + label + T.RESET)
        wrapped = wrap_display_text(msg.content, max(20, width - 4))
        for ln in wrapped:
            body.append("  " + ln)
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
