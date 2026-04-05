"""Shared text/layout helpers for ORBIT PTY interfaces.

These helpers intentionally stay ANSI-light and operate on plain text content
before higher-level renderers wrap fragments with styling.
"""

from __future__ import annotations

from . import termio as T


def fit_text(text: str, width: int) -> str:
    """Clip plain text to width with an ellipsis when needed."""
    text = text.replace("\n", " ").replace("\r", " ")
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def wrap_text(text: str, width: int) -> list[str]:
    """Word-wrap plain text into lines of at most ``width`` visible chars."""
    text = text.replace("\r", "").strip()
    if not text:
        return [""]
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        remaining = para
        while remaining:
            if len(remaining) <= width:
                lines.append(remaining)
                break
            cut = remaining[:width]
            sp = cut.rfind(" ")
            if sp > width // 2:
                lines.append(remaining[:sp])
                remaining = remaining[sp + 1 :]
            else:
                lines.append(remaining[:width])
                remaining = remaining[width:]
    return lines


def divider(width: int) -> str:
    """Return a muted purple horizontal divider spanning width."""
    return T.FG_MAGENTA + "─" * width + T.RESET


def header_text(text: str, width: int) -> str:
    """Return a clipped bright header line."""
    return T.BOLD + T.FG_BRIGHT_CYAN + fit_text(text, width) + T.RESET
