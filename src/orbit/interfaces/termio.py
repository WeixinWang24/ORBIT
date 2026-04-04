"""Terminal I/O primitives for ORBIT PTY interface.

Ported from claude_code_src/src/ink/termio/ (TypeScript → Python).
Covers: CSI builder, DEC private modes, SGR colours, cursor helpers,
and terminal capability detection.
"""

from __future__ import annotations

import os

# ── Core ─────────────────────────────────────────────────────────────────────

ESC = "\x1b"
CSI_PREFIX = ESC + "["


def csi(*args: str | int) -> str:
    """Build a CSI escape sequence.

    Single arg  → raw body:             ESC [ <arg>
    Multi  args → params;final byte:    ESC [ p1;p2;…;pN final
    """
    if not args:
        return CSI_PREFIX
    if len(args) == 1:
        return f"{CSI_PREFIX}{args[0]}"
    params = args[:-1]
    final = args[-1]
    return f"{CSI_PREFIX}{';'.join(str(p) for p in params)}{final}"


# ── DEC Private Modes ─────────────────────────────────────────────────────────

def decset(mode: int) -> str:
    """CSI ? N h — enable DEC private mode."""
    return csi(f"?{mode}h")


def decreset(mode: int) -> str:
    """CSI ? N l — disable DEC private mode."""
    return csi(f"?{mode}l")


SHOW_CURSOR          = decset(25)
HIDE_CURSOR          = decreset(25)
ENTER_ALT_SCREEN     = decset(1049)    # save cursor + clear + switch to alt
EXIT_ALT_SCREEN      = decreset(1049)  # switch back + restore cursor

# Mouse tracking (normal + button-motion + any-motion + SGR encoding)
ENABLE_MOUSE         = decset(1000) + decset(1002) + decset(1003) + decset(1006)
DISABLE_MOUSE        = decreset(1006) + decreset(1003) + decreset(1002) + decreset(1000)

ENABLE_BRACKETED_PASTE  = decset(2004)
DISABLE_BRACKETED_PASTE = decreset(2004)
ENABLE_FOCUS_EVENTS     = decset(1004)
DISABLE_FOCUS_EVENTS    = decreset(1004)

# DEC 2026 — Synchronized Update: wrap a frame in BSU/ESU to prevent flicker
BSU = decset(2026)   # Begin Synchronized Update
ESU = decreset(2026) # End   Synchronized Update

# Extended key reporting (Kitty keyboard protocol)
ENABLE_KITTY_KEYBOARD  = csi(">1u")
DISABLE_KITTY_KEYBOARD = csi("<u")

# ── Input markers sent FROM terminal to app ───────────────────────────────────

# Bracketed paste (DEC 2004)
PASTE_START = csi("200~")
PASTE_END   = csi("201~")

# Focus events (DEC 1004)
FOCUS_IN  = csi("I")
FOCUS_OUT = csi("O")


# ── Cursor Movement ───────────────────────────────────────────────────────────

def cursor_up(n: int = 1) -> str:
    return "" if n == 0 else csi(n, "A")


def cursor_down(n: int = 1) -> str:
    return "" if n == 0 else csi(n, "B")


def cursor_forward(n: int = 1) -> str:
    return "" if n == 0 else csi(n, "C")


def cursor_back(n: int = 1) -> str:
    return "" if n == 0 else csi(n, "D")


def cursor_to_col(col: int) -> str:
    """Move cursor to 1-indexed column."""
    return csi(col, "G")


def cursor_position(row: int, col: int) -> str:
    """Move cursor to 1-indexed (row, col)."""
    return csi(row, col, "H")


CURSOR_HOME = csi("H")       # row 1, col 1
CURSOR_LEFT = csi("G")       # col 1 of current row


def erase_lines(n: int) -> str:
    """Erase n lines upward (log-update style), leaving cursor at col 1."""
    if n <= 0:
        return ""
    result = ""
    for i in range(n):
        result += ERASE_LINE
        if i < n - 1:
            result += cursor_up(1)
    return result + CURSOR_LEFT


# ── Erase ─────────────────────────────────────────────────────────────────────

ERASE_SCREEN     = csi(2, "J")    # clear entire screen
ERASE_SCREEN_DOWN = csi("J")      # clear from cursor to end of screen
ERASE_LINE       = csi(2, "K")    # clear entire current line
ERASE_LINE_END   = csi("K")       # clear from cursor to end of line


# ── SGR (Select Graphic Rendition) ───────────────────────────────────────────

def sgr(*codes: int) -> str:
    """Build an SGR escape sequence: ESC [ code1;code2;… m"""
    return f"{CSI_PREFIX}{';'.join(str(c) for c in codes)}m"


# Attributes
RESET      = sgr(0)
BOLD       = sgr(1)
DIM        = sgr(2)
ITALIC     = sgr(3)
UNDERLINE  = sgr(4)
BLINK      = sgr(5)
INVERSE    = sgr(7)
NO_INVERSE = sgr(27)
NO_BOLD    = sgr(22)
NO_DIM     = sgr(22)
NO_ITALIC  = sgr(23)
NO_UNDERLINE = sgr(24)

# Foreground colours (standard)
FG_BLACK   = sgr(30)
FG_RED     = sgr(31)
FG_GREEN   = sgr(32)
FG_YELLOW  = sgr(33)
FG_BLUE    = sgr(34)
FG_MAGENTA = sgr(35)
FG_CYAN    = sgr(36)
FG_WHITE   = sgr(37)
FG_DEFAULT = sgr(39)

# Foreground colours (bright)
FG_BRIGHT_BLACK   = sgr(90)   # grey
FG_BRIGHT_RED     = sgr(91)
FG_BRIGHT_GREEN   = sgr(92)
FG_BRIGHT_YELLOW  = sgr(93)
FG_BRIGHT_BLUE    = sgr(94)
FG_BRIGHT_MAGENTA = sgr(95)
FG_BRIGHT_CYAN    = sgr(96)
FG_BRIGHT_WHITE   = sgr(97)

# Background colours
BG_BLACK   = sgr(40)
BG_RED     = sgr(41)
BG_GREEN   = sgr(42)
BG_YELLOW  = sgr(43)
BG_BLUE    = sgr(44)
BG_MAGENTA = sgr(45)
BG_CYAN    = sgr(46)
BG_WHITE   = sgr(47)
BG_DEFAULT = sgr(49)
BG_BRIGHT_BLACK = sgr(100)
BG_BRIGHT_WHITE = sgr(107)


def fg_rgb(r: int, g: int, b: int) -> str:
    """24-bit foreground colour (requires TRUECOLOR support)."""
    return f"{CSI_PREFIX}38;2;{r};{g};{b}m"


def bg_rgb(r: int, g: int, b: int) -> str:
    """24-bit background colour."""
    return f"{CSI_PREFIX}48;2;{r};{g};{b}m"


def fg_256(n: int) -> str:
    """256-colour foreground (0–255)."""
    return f"{CSI_PREFIX}38;5;{n}m"


def bg_256(n: int) -> str:
    """256-colour background."""
    return f"{CSI_PREFIX}48;5;{n}m"


# ── Terminal Capability Detection ─────────────────────────────────────────────

def is_synchronized_output_supported() -> bool:
    """True if terminal supports DEC 2026 (BSU/ESU eliminate redraw flicker).

    Detection mirrors claude_code_src terminal.ts isSynchronizedOutputSupported().
    tmux is excluded because it chunks output and breaks atomicity even when
    it proxies the BSU/ESU bytes to the outer terminal.
    """
    if os.environ.get("TMUX"):
        return False

    term_program = os.environ.get("TERM_PROGRAM", "")
    term = os.environ.get("TERM", "")

    if term_program in (
        "iTerm.app", "WezTerm", "WarpTerminal", "ghostty",
        "contour", "vscode", "alacritty",
    ):
        return True
    if "kitty" in term or os.environ.get("KITTY_WINDOW_ID"):
        return True
    if term == "xterm-ghostty":
        return True
    if term.startswith("foot"):
        return True
    if "alacritty" in term:
        return True
    if os.environ.get("ZED_TERM"):
        return True
    if os.environ.get("WT_SESSION"):
        return True

    vte = os.environ.get("VTE_VERSION", "")
    if vte:
        try:
            if int(vte) >= 6800:
                return True
        except ValueError:
            pass

    return False


def supports_truecolor() -> bool:
    """True if terminal supports 24-bit RGB colour."""
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return True
    term_program = os.environ.get("TERM_PROGRAM", "")
    term = os.environ.get("TERM", "")
    return (
        term_program in ("iTerm.app", "WezTerm", "ghostty", "vscode")
        or "256color" in term
    )


# Pre-computed once at import time — capabilities don't change mid-session.
SYNC_OUTPUT = is_synchronized_output_supported()
TRUECOLOR   = supports_truecolor()
