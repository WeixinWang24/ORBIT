"""Shared PTY terminal primitives for ORBIT terminal interfaces.

This module centralizes the low-level alternate-screen / raw-mode / mouse /
focus / bracketed-paste helpers and the diff-based screen renderer used by the
runtime workbench surfaces.

Design intent:
- keep terminal plumbing out of higher-level CLI/workbench modules
- let both `pty_runtime_cli.py` and `pty_workbench.py` share one rendering core
- make the runtime-first CLI easier to split into state / render / handler layers
"""

from __future__ import annotations

import shutil
import sys
import tty
from contextlib import contextmanager
from termios import TCSADRAIN, tcgetattr, tcsetattr
from typing import Generator

from . import termio as T


def terminal_size() -> tuple[int, int]:
    """Return a bounded terminal size fallback suitable for ORBIT PTY UIs."""
    s = shutil.get_terminal_size((100, 32))
    return max(40, s.columns), max(16, s.lines)


class ScreenBuffer:
    """Incremental screen renderer with full-repaint invalidation support."""

    def __init__(self) -> None:
        self._prev: list[str] = []

    def render(self, lines: list[str], width: int, height: int, *, force_full_repaint: bool = False) -> None:
        padded = [ln for ln in lines[:height]]
        while len(padded) < height:
            padded.append("")

        first = not self._prev
        shape_changed = self._prev and len(self._prev) != height

        buf = T.HIDE_CURSOR
        if T.SYNC_OUTPUT:
            buf += T.BSU

        if force_full_repaint or first or shape_changed:
            buf += T.ERASE_SCREEN + T.CURSOR_HOME
            for i, line in enumerate(padded):
                buf += line
                if i < height - 1:
                    buf += "\r\n"
        else:
            for i, (old, new) in enumerate(zip(self._prev, padded)):
                if old != new:
                    buf += T.cursor_position(i + 1, 1)
                    buf += T.ERASE_LINE_END
                    buf += new
            for i in range(len(self._prev), len(padded)):
                buf += T.cursor_position(i + 1, 1)
                buf += T.ERASE_LINE_END
                buf += padded[i]

        if T.SYNC_OUTPUT:
            buf += T.ESU
        buf += T.SHOW_CURSOR

        sys.stdout.write(buf)
        sys.stdout.flush()
        self._prev = padded

    def invalidate(self) -> None:
        self._prev = []


@contextmanager
def raw_mode() -> Generator[None, None, None]:
    """Enter raw terminal mode when stdin is a TTY."""
    if not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        tcsetattr(fd, TCSADRAIN, old)


@contextmanager
def alt_screen() -> Generator[None, None, None]:
    """Switch into the terminal alternate screen for the duration."""
    sys.stdout.write(T.ENTER_ALT_SCREEN)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(T.EXIT_ALT_SCREEN)
        sys.stdout.flush()


@contextmanager
def mouse_tracking() -> Generator[None, None, None]:
    """Enable SGR mouse reporting for the duration."""
    sys.stdout.write(T.ENABLE_MOUSE)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(T.DISABLE_MOUSE)
        sys.stdout.flush()


@contextmanager
def bracketed_paste() -> Generator[None, None, None]:
    """Enable bracketed paste markers for the duration."""
    sys.stdout.write(T.ENABLE_BRACKETED_PASTE)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(T.DISABLE_BRACKETED_PASTE)
        sys.stdout.flush()


@contextmanager
def focus_events() -> Generator[None, None, None]:
    """Enable focus in/out terminal events for the duration."""
    sys.stdout.write(T.ENABLE_FOCUS_EVENTS)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(T.DISABLE_FOCUS_EVENTS)
        sys.stdout.flush()
