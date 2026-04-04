"""Chat viewport/window state for the runtime-first ORBIT PTY CLI.

First slice:
- centralize visible-window computation for chat body lines
- replace ad hoc bottom-slice math in frame rendering
- create a stable home for future bottom-anchor vs free-scroll behavior
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatViewportState:
    scroll_offset: int = 0
    anchor_to_bottom: bool = True
    last_total_lines: int = 0
    last_viewport_height: int = 0


@dataclass
class ChatViewportRender:
    visible_lines: list[str]
    max_scroll: int
    applied_scroll_offset: int
    applied_anchor_to_bottom: bool


def compute_chat_viewport(*, lines: list[str], viewport_height: int, state: ChatViewportState) -> ChatViewportRender:
    viewport_height = max(1, viewport_height)
    total_lines = len(lines)
    max_scroll = max(0, total_lines - viewport_height)

    if state.anchor_to_bottom:
        applied_scroll_offset = 0
    else:
        applied_scroll_offset = max(0, min(state.scroll_offset, max_scroll))

    end = total_lines - applied_scroll_offset
    start = max(0, end - viewport_height)
    visible_lines = lines[start:end]

    state.last_total_lines = total_lines
    state.last_viewport_height = viewport_height
    state.scroll_offset = applied_scroll_offset
    if applied_scroll_offset == 0:
        state.anchor_to_bottom = True

    return ChatViewportRender(
        visible_lines=visible_lines,
        max_scroll=max_scroll,
        applied_scroll_offset=applied_scroll_offset,
        applied_anchor_to_bottom=state.anchor_to_bottom,
    )
