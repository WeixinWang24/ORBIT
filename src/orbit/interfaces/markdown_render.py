"""Markdown → ANSI terminal line renderer for the ORBIT PTY CLI.

Design contract
---------------
- Input:  plain markdown text + a display width (in terminal columns).
- Output: a ``tuple[str, ...]`` of pre-wrapped, ANSI-coded lines.
- The caller (chat_projection.py) prepends its own indent prefix and feeds
  lines directly into the body list.  Lines must NOT be re-wrapped after
  being returned here — they are already wrapped to ``width``.

What uses this
--------------
- Ordinary committed user / assistant messages in chat mode.

What must NOT use this
----------------------
- ``assistant_inflight_text`` (streaming): partial markdown produces broken
  output (unclosed fences render as giant code blocks, lone ``**`` is literal).
  The streaming path stays on ``wrap_display_text()``.
- ``tool_result`` rows: those have a separate compact single-line format.
- Control / approval / policy messages: those need plain text without any
  markdown interpretation.
- Any message whose ``message_kind`` is not ``None``: the presence of a kind
  tag signals special handling that markdown would interfere with.

Caching
-------
``render_markdown`` is cached with ``@lru_cache(maxsize=256)`` keyed on
``(text, width)``.  Committed messages are immutable, so the hit-rate is
near 100%.  On terminal resize the new width produces new cache entries;
stale width entries evict naturally via LRU.  256 slots cover ~12 distinct
terminal widths × 20-message history with headroom.

Code fence style
----------------
``code_theme="none"`` suppresses Pygments syntax-token coloring inside fenced
blocks.  The panel/container background (a grey fill) is a Rich container
style, not a Pygments theme, so it is preserved — this is intentional and
acceptable for the MVP.  Syntax highlighting can be enabled in a later stage
by exposing a ``code_theme`` parameter.

Trailing whitespace
-------------------
Rich pads rendered lines with trailing spaces to fill the requested terminal
width.  For lines that end in plain spaces (paragraphs, list items, numbered
items) we strip them with ``rstrip(' ')``.  For lines that end in an ANSI
reset sequence (blockquotes, code-block borders) the padding spaces appear
*before* the reset code — ``rstrip(' ')`` leaves those alone, preserving the
intentional background-color fill.
"""

from __future__ import annotations

import io
import re
from functools import lru_cache

from rich.console import Console
from rich.markdown import Markdown

from . import termio as T


LIGHT_CODE_BG_PATTERNS = (
    "\x1b[47m",
    "\x1b[107m",
    "\x1b[48;2;248;248;248m",
    "\x1b[48;2;250;250;250m",
    "\x1b[48;5;255m",
)
MUTED_CODE_BG = T.bg_rgb(58, 58, 62)
MUTED_CODE_FG = T.fg_rgb(214, 214, 214)
MUTED_HEADING = T.fg_rgb(220, 208, 255) + T.BOLD
MUTED_HEADING_DIVIDER = T.fg_rgb(120, 104, 160)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _normalize_emoji_for_terminal(text: str) -> str:
    """Reduce known terminal-width troublemakers in markdown-rendered text.

    Some emoji/glyph presentation sequences render wider in the terminal than
    the upstream wrapping logic expects, especially when variation selectors
    are involved.  This can produce clipped right halves (observed with ✅).
    For the markdown path, prefer a more stable text presentation.
    """
    return text.replace("\ufe0f", "")


def _soften_code_block_background(lines: list[str]) -> list[str]:
    softened: list[str] = []
    for ln in lines:
        updated = ln
        for pattern in LIGHT_CODE_BG_PATTERNS:
            updated = updated.replace(pattern, MUTED_CODE_BG)
        if MUTED_CODE_BG in updated and T.FG_DEFAULT in updated:
            updated = updated.replace(T.FG_DEFAULT, MUTED_CODE_FG)
        softened.append(updated)
    return softened


def _rewrite_heavy_h1_box(lines: list[str], width: int) -> list[str]:
    if len(lines) < 3:
        return lines
    rewritten: list[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            top_plain = _strip_ansi(lines[i]).strip()
            mid_plain = _strip_ansi(lines[i + 1]).strip()
            bot_plain = _strip_ansi(lines[i + 2]).strip()
            if top_plain.startswith("┏") and top_plain.endswith("┓") and mid_plain.startswith("┃") and mid_plain.endswith("┃") and bot_plain.startswith("┗") and bot_plain.endswith("┛"):
                title = mid_plain.strip("┃").strip()
                if title:
                    divider_width = max(6, min(width, max(len(title), 12)))
                    rewritten.append(MUTED_HEADING + title + T.RESET)
                    rewritten.append(MUTED_HEADING_DIVIDER + ("─" * divider_width) + T.RESET)
                    i += 3
                    continue
        rewritten.append(lines[i])
        i += 1
    return rewritten


@lru_cache(maxsize=256)
def render_markdown(text: str, width: int) -> tuple[str, ...]:
    """Render *text* as markdown and return pre-wrapped ANSI terminal lines.

    Parameters
    ----------
    text:
        Raw markdown string from a committed user or assistant message.
    width:
        Available display-column budget for this message body (the caller's
        ``width - 4`` value, *before* the 2-space indent prefix is applied).

    Returns
    -------
    A non-empty tuple of strings.  Each string is a single terminal line with
    embedded ANSI escape codes.  Lines contain no ``\\n`` characters and are
    already wrapped to *width* display columns.
    """
    if not text or not text.strip():
        return ("",)

    text = _normalize_emoji_for_terminal(text)

    buf = io.StringIO()
    console = Console(
        file=buf,
        force_terminal=True,   # emit ANSI codes even though target is StringIO
        width=width,
        highlight=False,       # disable Rich's auto-highlighter (IP, paths, etc.)
        no_color=False,        # keep markdown-driven colours
    )
    # hyperlinks=False: suppress OSC-8 escape sequences; raw PTY support is
    # unreliable across terminals and it clutters the diff-based renderer.
    # code_theme="none": no Pygments syntax colouring in this MVP.
    try:
        md = Markdown(text, hyperlinks=False, code_theme="none")
        console.print(md, end="")
    except Exception:
        # Defensive fallback: if Rich fails to parse (shouldn't happen in
        # practice), return the text as a single plain line so the UI
        # doesn't crash.
        return (text.replace("\n", " "),)

    raw = buf.getvalue()
    lines = raw.split("\n")

    # Rich appends a trailing "\n" which produces a spurious empty final
    # element after split — remove all trailing empty strings.
    while lines and lines[-1] == "":
        lines.pop()

    if not lines:
        return ("",)

    # Strip trailing plain-space padding that Rich adds to fill terminal width.
    # ``rstrip(' ')`` is safe here:
    #   - Paragraphs / list items / numbered items end in spaces → stripped.
    #   - Blockquote / code-block lines end in an ANSI reset code after the
    #     spaces, so the spaces sit before the reset; ``rstrip(' ')`` won't
    #     reach them and the intentional background colour fill is preserved.
    lines = [ln.rstrip(" ") for ln in lines]

    # ORBIT-local visual polish:
    # - tone down Rich's very bright code-block container background so it fits
    #   dark terminals better
    # - rewrite heavy H1 title boxes into a lighter title + divider treatment
    lines = _soften_code_block_background(lines)
    lines = _rewrite_heavy_h1_box(lines, width)

    return tuple(lines)
