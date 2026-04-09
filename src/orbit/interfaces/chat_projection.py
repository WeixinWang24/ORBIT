"""Chat projection helpers for the runtime-first ORBIT PTY CLI.

First slice:
- centralize projection of current session transcript into renderable lines
- keep transcript projection separate from fixed shell/header status
- leave an obvious extension point for future assistant delta / inflight rendering
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from unicodedata import east_asian_width as _eaw

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _visible_len(s: str) -> int:
    """Return the visible *column* width of *s* after stripping ANSI escapes.

    Wide characters (CJK ideographs, fullwidth forms) occupy 2 terminal
    columns each; everything else counts as 1.
    """
    plain = _ANSI_RE.sub("", s)
    return sum(2 if _eaw(ch) in ("W", "F") else 1 for ch in plain)

from . import termio as T
from .composer_state import wrap_display_text
from .markdown_render import render_markdown

# Matches SGR full-reset sequences: ESC[0m and ESC[m (both are valid resets).
_SGR_RESET_RE = re.compile(r"\x1b\[0?m")


def _paint_line(ln: str, color: str) -> str:
    """Apply *color* as the persistent base foreground for a rendered line.

    Rich emits ``ESC[0m`` after every inline style span (bold, code, etc.).
    That full SGR reset wipes our base color, leaving subsequent plain text
    at the terminal default.  We fix this by replacing every reset with
    ``reset + color`` so the base color is restored after each span, then
    wrapping the whole line in ``color … reset``.

    Empty / whitespace-only lines are returned unchanged (no color needed).
    """
    if not ln.strip():
        return ln
    # Re-apply base color after every inline reset.
    recolored = _SGR_RESET_RE.sub("\x1b[0m" + color, ln)
    return color + recolored + "\x1b[0m"


@dataclass
class ChatProjection:
    lines: list[str]
    session_id: str
    has_busy_banner: bool = False
    assistant_inflight_text: str | None = None


def _compact_tool_result_label(msg, width: int) -> str:
    metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
    tool_projection = metadata.get("tool_projection") if isinstance(metadata.get("tool_projection"), dict) else {}
    tool_name = tool_projection.get("tool_name") or metadata.get("tool_name") or "unknown"
    message_kind = msg.message_kind or metadata.get("message_kind") or "tool_result"
    if message_kind == "capability_result":
        status = "ok"
    elif message_kind == "approval_result":
        status = "waiting for approval"
    elif message_kind == "runtime_failure":
        status = "error"
    else:
        lowered = (msg.content or "").strip().lower()
        if "outside_allowed_root" in lowered or "blocked" in lowered or "deny" in lowered:
            status = "blocked"
        elif lowered:
            status = "ok"
        else:
            status = "done"
    line = f"Tool result · {tool_name} · {status}"
    max_width = max(20, width)
    if len(line) > max_width:
        line = line[: max(0, max_width - 1)] + "…"
    return line


def build_chat_projection(*, adapter, session_id: str, width: int, runtime_busy: bool, pending_submit_session_id: str | None, pending_submit_text: str, submit_started_at: float | None, assistant_inflight_text: str | None, accent_user: str, accent_assistant: str, accent_warning: str, accent_muted: str, content_user: str = "", content_assistant: str = "", approval_picker_index: int = 0, approval_action_pending: bool = False, approval_action_label: str | None = None, chat_history_limit: int = 20) -> ChatProjection:
    lines: list[str] = []
    body: list[str] = []
    hidden_kinds = {
        "approval_request",
        "approval_guidance",
        "structured_reauthorization",
        "approval_decision",
        "approval_result",
    }
    messages = adapter.list_messages(session_id)
    if chat_history_limit > 0:
        messages = messages[-chat_history_limit:]
    for msg in messages:
        if msg.message_kind in hidden_kinds:
            continue
        label = msg.role.upper() if not msg.message_kind else f"{msg.role.upper()} [{msg.message_kind}]"

        # ── TOOL result ───────────────────────────────────────────────────
        if msg.role == "tool" or msg.message_kind in {"tool_result", "capability_result"}:
            body.append(accent_assistant + _compact_tool_result_label(msg, width) + T.RESET)
            body.append("")
            continue

        # ── User message — bubble-right layout ───────────────────────────
        if msg.role == "user":
            # Render at max bubble width first (min_indent=18, right_margin=1).
            _min_indent = 18
            _right_margin = 1
            bubble_width = max(20, width - _min_indent - _right_margin)
            if msg.message_kind is None:
                content_lines: tuple[str, ...] | list[str] = render_markdown(
                    msg.content, bubble_width
                )
            else:
                content_lines = wrap_display_text(msg.content, bubble_width)
            # Compute indent so the longest line's right edge touches the border.
            max_line_len = max(
                (_visible_len(ln) for ln in content_lines if ln.strip()),
                default=0,
            )
            indent = max(_min_indent, width - max_line_len - _right_margin)
            indent_str = " " * indent
            # Label right-aligned to terminal width.
            body.append(" " * max(0, width - len(label)) + accent_user + label + T.RESET)
            for ln in content_lines:
                body.append(indent_str + _paint_line(ln, content_user))
            body.append("")
            continue

        # ── Assistant / system / other ────────────────────────────────────
        color = accent_assistant if msg.role == "assistant" else accent_warning
        body.append(color + label + T.RESET)
        # Apply markdown rendering only for ordinary committed chat messages
        # (message_kind is None).  Messages with an explicit kind tag carry
        # special control semantics (errors, policy notices, system events)
        # that should be presented as plain text without markdown
        # interpretation.  Streaming / inflight text is handled separately
        # below and stays on wrap_display_text() throughout.
        content_width = max(20, width - 4)
        if msg.message_kind is None and msg.role == "assistant":
            content_lines = render_markdown(msg.content, content_width)
        else:
            content_lines = wrap_display_text(msg.content, content_width)
        content_color = content_assistant if msg.role == "assistant" else ""
        for ln in content_lines:
            if content_color:
                body.append("  " + _paint_line(ln, content_color))
            else:
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
