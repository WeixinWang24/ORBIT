"""Markdown → ANSI terminal line renderer for the ORBIT PTY CLI.

Design contract
---------------
- Input:  plain markdown text + a display width (in terminal columns).
- Output: a ``tuple[str, ...]`` of pre-wrapped, ANSI-coded lines.
- The caller (chat_projection.py) prepends its own indent prefix and feeds
  lines directly into the body list. Lines must NOT be re-wrapped after
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
``(text, width)``. Committed messages are immutable, so the hit-rate is near
100%. On terminal resize the new width produces new cache entries; stale width
entries evict naturally via LRU.

Fenced code blocks
------------------
Fenced code blocks use Rich's built-in dark ``monokai`` theme. This keeps the
container background and token spans consistently dark, which works much better
for ORBIT's dark terminal than Rich's default bright code-block presentation.

H1 headings
-----------
Rich's default H1 rendering is visually loud (heavy box chrome). ORBIT rewrites
that three-line box into a lighter treatment:
- one title line in a muted bright heading colour
- one soft purple divider line underneath

Emoji / status glyphs
---------------------
Some terminals render certain emoji/status sequences unreliably inside the raw
PTY path (for example clipped right halves or odd fallback glyphs). For the
markdown path we normalize a few high-risk symbols into stable text forms.
"""

from __future__ import annotations

import io
import re
from functools import lru_cache

from rich.console import Console
from rich.markdown import Markdown

from . import termio as T

_CODE_THEME = "monokai"
MUTED_HEADING = T.fg_rgb(220, 208, 255) + T.BOLD
MUTED_HEADING_DIVIDER = T.fg_rgb(120, 104, 160)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _normalize_emoji_for_terminal(text: str) -> str:
    return (
        text.replace("\ufe0f", "")
        .replace("✅", "[OK]")
        .replace("☑", "[DONE]")
    )


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
            if (
                top_plain.startswith("┏")
                and top_plain.endswith("┓")
                and mid_plain.startswith("┃")
                and mid_plain.endswith("┃")
                and bot_plain.startswith("┗")
                and bot_plain.endswith("┛")
            ):
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
    """Render *text* as markdown and return pre-wrapped ANSI terminal lines."""
    if not text or not text.strip():
        return ("",)

    text = _normalize_emoji_for_terminal(text)

    buf = io.StringIO()
    console = Console(
        file=buf,
        force_terminal=True,
        width=width,
        highlight=False,
        no_color=False,
    )
    try:
        md = Markdown(text, hyperlinks=False, code_theme=_CODE_THEME)
        console.print(md, end="")
    except Exception:
        return (text.replace("\n", " "),)

    raw = buf.getvalue()
    lines = raw.split("\n")

    while lines and lines[-1] == "":
        lines.pop()

    if not lines:
        return ("",)

    lines = [ln.rstrip(" ") for ln in lines]
    lines = _rewrite_heavy_h1_box(lines, width)
    return tuple(lines)
