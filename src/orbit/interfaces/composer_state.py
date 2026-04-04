"""Composer input state for the runtime-first ORBIT PTY CLI.

First slice inspired by the more mature Claude Code input-state split:
- keep multiline text state out of render helpers
- centralize display-width-aware wrapping and cursor layout
- let render consume structured composer output instead of reconstructing it
"""

from __future__ import annotations

from dataclasses import dataclass
from unicodedata import east_asian_width

from . import termio as T


@dataclass
class ComposerRenderState:
    lines: list[str]
    cursor_row_offset: int
    cursor_col: int
    pulse_tick: int | None = None


@dataclass
class ComposerState:
    text: str = ""

    def insert_text(self, text: str) -> None:
        self.text += text

    def insert_newline(self) -> None:
        self.text += "\n"

    def backspace(self) -> None:
        self.text = self.text[:-1]


def display_width(text: str) -> int:
    width = 0
    for ch in text:
        width += 2 if east_asian_width(ch) in {"W", "F"} else 1
    return width


def wrap_display_text(text: str, width: int) -> list[str]:
    """Wrap text into display-width-aware lines.

    ``\n`` is treated as a hard line break (split before wrapping each
    paragraph), so lines in the result never contain embedded newline chars.
    This prevents terminal staircase artifacts when rendered via raw PTY writes.
    """
    if width <= 1:
        return [text[:1]] if text else [""]
    if not text:
        return [""]
    result: list[str] = []
    for para in text.split("\n"):
        if not para:
            result.append("")
            continue
        current: list[str] = []
        current_width = 0
        for ch in para:
            ch_width = display_width(ch)
            if current and current_width + ch_width > width:
                result.append("".join(current))
                current = [ch]
                current_width = ch_width
            else:
                current.append(ch)
                current_width += ch_width
        if current:
            result.append("".join(current))
    return result or [""]


def render_composer(state: ComposerState, *, width: int, chat_mode: bool, pulse_tick: int | None = None) -> ComposerRenderState:
    if not chat_mode:
        return ComposerRenderState(lines=[T.DIM + "[NAV] " + T.RESET + "Navigation mode"], cursor_row_offset=0, cursor_col=1, pulse_tick=None)

    prefix_plain = "[INPUT] > "
    prefix_color = T.FG_BRIGHT_GREEN
    prefix = prefix_color + T.BOLD + prefix_plain + T.RESET
    body_width = max(1, width - display_width(prefix_plain))
    wrapped = wrap_display_text(state.text, body_width) if state.text else [""]
    lines = [prefix + wrapped[0]]
    indent = " " * len(prefix_plain)
    for extra in wrapped[1:]:
        lines.append(indent + extra)
    cursor_row_offset = len(lines) - 1
    cursor_col = display_width(indent if len(lines) > 1 else prefix_plain) + display_width(wrapped[-1]) + 1
    return ComposerRenderState(lines=lines, cursor_row_offset=cursor_row_offset, cursor_col=cursor_col, pulse_tick=pulse_tick)
