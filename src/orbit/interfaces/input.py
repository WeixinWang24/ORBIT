"""Keyboard and mouse input parser for ORBIT PTY interface.

Ported from claude_code_src/src/ink/parse-keypress.ts (TypeScript → Python).

Handles:
  - Standard ANSI arrow / function key sequences
  - CSI u  (Kitty keyboard protocol)
  - xterm  modifyOtherKeys  (ESC [ 27 ; mod ; key ~)
  - SGR    mouse events     (click, drag, scroll wheel)
  - Bracketed paste markers (DEC 2004)
  - Focus event markers     (DEC 1004)

Current note (v4):
  - `read_sequence()` carries a small persistent pending buffer + age counter.
  - Broken ESC-prefixed sequences are reassembled across loop iterations.
  - Bare ESC is now a complete sequence, so the Escape key always fires.
  - DCS / OSC / PM / APC intro bytes are included in the fragment detector.
  - Stale fragments are force-flushed after `_PENDING_MAX_AGE` consecutive
    reads with no growth, preventing indefinite input blocking.
  - SS3 completions are validated against the known `_SS3_LETTER` set.
"""

from __future__ import annotations

import os
import re
import select
import sys
from dataclasses import dataclass

ESC = "\x1b"
_INPUT_DEBUG_ENABLED = os.environ.get("ORBIT_PTY_DEBUG", "").lower() in {"1", "true", "yes", "on"}
_INPUT_DEBUG_PATH = "/Volumes/2TB/MAS/openclaw-core/ORBIT/.tmp/orbit_pty_debug.log"
_INPUT_DEBUG_VERSION = "input_read_sequence_v4"
_PENDING_SEQ = ""
# How many consecutive read calls a control fragment may be held before forced
# flush.  Guards against bare-ESC and other stale fragments blocking forever.
_PENDING_AGE = 0
_PENDING_MAX_AGE = 3


def _input_debug(message: str) -> None:
    if not _INPUT_DEBUG_ENABLED:
        return
    os.makedirs(os.path.dirname(_INPUT_DEBUG_PATH), exist_ok=True)
    with open(_INPUT_DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{_INPUT_DEBUG_VERSION}:{message}\n")


# ── Compiled regex patterns ───────────────────────────────────────────────────

_CSI_U_RE = re.compile(r"^\x1b\[(\d+)(?:;(\d+))?u$")
_MOK_RE = re.compile(r"^\x1b\[27;(\d+);(\d+)~$")
_SGR_MOUSE_RE = re.compile(r"^\x1b\[<(\d+);(\d+);(\d+)([Mm])$")
_META_RE = re.compile(r"^\x1b([a-zA-Z0-9])$")


@dataclass
class ParsedKey:
    name: str
    sequence: str
    ctrl: bool = False
    meta: bool = False
    shift: bool = False
    fn: bool = False
    is_pasted: bool = False


@dataclass
class ParsedMouse:
    col: int
    row: int
    button: int
    pressed: bool
    dragging: bool = False
    wheel_up: bool = False
    wheel_down: bool = False
    sequence: str = ""


@dataclass
class ParsedFocus:
    focused: bool
    sequence: str = ""


InputEvent = ParsedKey | ParsedMouse | ParsedFocus

_CSI_LETTER: dict[str, str | None] = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "E": "clear",
    "F": "end",
    "H": "home",
    "I": None,
    "O": None,
    "P": "F1",
    "Q": "F2",
    "R": "F3",
    "S": "F4",
    "Z": "tab",
}

_SS3_LETTER: dict[str, str] = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "F": "end",
    "H": "home",
    "P": "F1",
    "Q": "F2",
    "R": "F3",
    "S": "F4",
}

_VT_TILDE: dict[int, str | None] = {
    1: "home",
    2: "insert",
    3: "delete",
    4: "end",
    5: "pageup",
    6: "pagedown",
    7: "home",
    8: "end",
    11: "F1", 12: "F2", 13: "F3", 14: "F4",
    15: "F5", 17: "F6", 18: "F7", 19: "F8",
    20: "F9", 21: "F10", 23: "F11", 24: "F12",
    25: "F13", 26: "F14", 28: "F15", 29: "F16",
    31: "F17", 32: "F18", 33: "F19", 34: "F20",
    200: None,
    201: None,
}

_CSI_U_NAMES: dict[int, str] = {
    9: "tab", 13: "enter", 27: "escape", 127: "backspace",
    57399: "F1", 57400: "F2", 57401: "F3", 57402: "F4",
    57403: "F5", 57404: "F6", 57405: "F7", 57406: "F8",
    57407: "F9", 57408: "F10", 57409: "F11", 57410: "F12",
    57415: "insert", 57416: "delete",
    57417: "left", 57418: "right",
    57419: "up", 57420: "down",
    57421: "pageup", 57422: "pagedown",
    57423: "home", 57424: "end",
}

_CTRL_CODES: dict[int, str] = {
    1: "a", 2: "b", 3: "c", 4: "d", 5: "e", 6: "f", 7: "g",
    8: "backspace", 9: "tab", 10: "j", 11: "k", 12: "l",
    13: "enter", 14: "n", 15: "o", 16: "p", 17: "q",
    18: "r", 19: "s", 20: "t", 21: "u", 22: "v", 23: "w",
    24: "x", 25: "y", 26: "z",
    27: "escape",
    28: "\\",
    29: "]",
    30: "^",
    31: "_",
    127: "backspace",
}


def _decode_modifiers(m: int) -> tuple[bool, bool, bool, bool]:
    v = m - 1
    return bool(v & 1), bool(v & 2), bool(v & 4), bool(v & 8)


def _read_available_char(timeout_s: float) -> str | None:
    r, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not r:
        return None
    c = sys.stdin.read(1)
    return c or None


def _looks_like_control_fragment(text: str) -> bool:
    """Return True if *text* looks like an incomplete ESC-prefixed control sequence.

    A bare ESC is NOT considered a fragment here: `_is_sequence_complete` already
    returns True for it, so there is nothing left to accumulate.  Without this
    exclusion, a bare Escape key would be held forever (the old v3 bug).

    The character set is extended to include DCS/OSC/PM/APC intro bytes
    (P, ], ^, _) and SS3 letter candidates (R, S) that were missing before.
    """
    if not text:
        return False
    if text == ESC:
        # Bare ESC: complete on its own, do not hold.
        return False
    if text.startswith(ESC):
        text = text[1:]
    if not text:
        return False
    return all(ch in "[O;<~ABCDHFMmPRS]^_0123456789" for ch in text)


def read_sequence(timeout_ms: float = 50.0) -> str:
    """Read one terminal input sequence from stdin.

    v4 behavior:
    - keeps a small persistent `_PENDING_SEQ` with an age counter
    - ESC-prefixed fragments are held across iterations until complete
    - bare ESC is now recognised as a complete sequence and never held forever
    - DCS / OSC / PM / APC intro bytes are included in the fragment detector
    - a fragment that fails to grow for `_PENDING_MAX_AGE` consecutive reads is
      force-flushed so stale data cannot block subsequent input indefinitely
    """
    global _PENDING_SEQ, _PENDING_AGE

    _input_debug("read_sequence:active")

    # If there is already a pending control fragment, try to grow it first.
    if _PENDING_SEQ:
        _input_debug(f"read_sequence:pending_start={_PENDING_SEQ!r} age={_PENDING_AGE}")
        timeout_s = max(0.005, timeout_ms / 1000.0)
        while True:
            if _is_sequence_complete(_PENDING_SEQ):
                out = _PENDING_SEQ
                _PENDING_SEQ = ""
                _PENDING_AGE = 0
                _input_debug(f"read_sequence:pending_complete={out!r}")
                return out
            nxt = _read_available_char(timeout_s)
            if nxt is None:
                if _looks_like_control_fragment(_PENDING_SEQ) and _PENDING_AGE < _PENDING_MAX_AGE:
                    _PENDING_AGE += 1
                    _input_debug(f"read_sequence:pending_hold={_PENDING_SEQ!r} age={_PENDING_AGE}")
                    return ""
                # Fragment timed out or exceeded max age – flush it.
                out = _PENDING_SEQ
                _PENDING_SEQ = ""
                _PENDING_AGE = 0
                _input_debug(f"read_sequence:pending_flush={out!r}")
                return out
            _PENDING_SEQ += nxt
            _PENDING_AGE = 0  # fragment grew – reset age
            _input_debug(f"read_sequence:pending_grow={_PENDING_SEQ!r}")

    ch = sys.stdin.read(1)
    if not ch:
        _input_debug("read_sequence:eof")
        return ""
    if ch != ESC:
        _input_debug(f"read_sequence:single={ch!r}")
        return ch

    buf = ch
    timeout_s = max(0.005, timeout_ms / 1000.0)

    nxt = _read_available_char(timeout_s)
    if nxt is None:
        # Nothing followed the ESC within the timeout.
        # _is_sequence_complete("\x1b") now returns True, so on the next call
        # the pending loop will immediately dispatch it as a bare Escape event.
        _PENDING_SEQ = buf
        _PENDING_AGE = 0
        _input_debug("read_sequence:bare_escape_pending")
        return ""
    buf += nxt
    _input_debug(f"read_sequence:after_escape_first={buf!r}")

    while True:
        if _is_sequence_complete(buf):
            _input_debug(f"read_sequence:complete={buf!r}")
            return buf
        nxt = _read_available_char(timeout_s)
        if nxt is None:
            if _looks_like_control_fragment(buf):
                _PENDING_SEQ = buf
                _PENDING_AGE = 0
                _input_debug(f"read_sequence:partial_store_pending={buf!r}")
                return ""
            _input_debug(f"read_sequence:partial_timeout_return={buf!r}")
            return buf
        buf += nxt
        _input_debug(f"read_sequence:grow={buf!r}")


def _is_sequence_complete(seq: str) -> bool:
    # A bare ESC is a complete event on its own (Escape key press).
    if seq == ESC:
        return True

    if len(seq) < 2:
        return False
    s1 = seq[1]

    if s1 == "O":
        # SS3 sequence: ESC O <letter>.  Require a valid SS3 terminator so we
        # don't prematurely complete on an arbitrary third byte.
        if len(seq) < 3:
            return False
        return seq[2] in _SS3_LETTER

    if s1 == "[":
        if len(seq) < 3:
            return False
        last = seq[-1]
        return "\x40" <= last <= "\x7e"

    if s1 == "P":
        # DCS: terminated by ST (ESC \)
        return seq.endswith("\x1b\\")

    if s1 in ("]", "^", "_"):
        # OSC / PM / APC: terminated by BEL or ST
        return seq.endswith("\x07") or seq.endswith("\x1b\\")

    return len(seq) >= 2


def parse_sequence(seq: str) -> InputEvent | None:
    if seq == "\x1b[I":
        return ParsedFocus(focused=True, sequence=seq)
    if seq == "\x1b[O":
        return ParsedFocus(focused=False, sequence=seq)

    if seq in ("\x1b[200~", "\x1b[201~"):
        return None

    m = _SGR_MOUSE_RE.match(seq)
    if m:
        btn_raw = int(m.group(1))
        col = int(m.group(2))
        row = int(m.group(3))
        pressed = m.group(4) == "M"
        return ParsedMouse(
            col=col,
            row=row,
            button=btn_raw & 3,
            pressed=pressed,
            dragging=bool(btn_raw & 32),
            wheel_up=(btn_raw == 64),
            wheel_down=(btn_raw == 65),
            sequence=seq,
        )

    m = _CSI_U_RE.match(seq)
    if m:
        codepoint = int(m.group(1))
        modifier = int(m.group(2) or "1")
        shift, alt, ctrl, _ = _decode_modifiers(modifier)
        name = _CSI_U_NAMES.get(codepoint) or (chr(codepoint) if codepoint < 0x110000 else str(codepoint))
        return ParsedKey(name=name, sequence=seq, ctrl=ctrl, meta=alt, shift=shift)

    m = _MOK_RE.match(seq)
    if m:
        modifier = int(m.group(1))
        codepoint = int(m.group(2))
        shift, alt, ctrl, _ = _decode_modifiers(modifier)
        name = _CSI_U_NAMES.get(codepoint) or (chr(codepoint) if codepoint < 0x110000 else str(codepoint))
        return ParsedKey(name=name, sequence=seq, ctrl=ctrl, meta=alt, shift=shift)

    if seq.startswith("\x1b[") and len(seq) >= 3:
        body = seq[2:]
        last = body[-1]

        if last == "~":
            parts = body[:-1].split(";", 1)
            try:
                n = int(parts[0])
            except ValueError:
                return None
            mod = int(parts[1]) if len(parts) > 1 else 1
            shift, alt, ctrl, _ = _decode_modifiers(mod)
            name = _VT_TILDE.get(n)
            if name is None:
                return None
            return ParsedKey(name=name, sequence=seq, ctrl=ctrl, meta=alt, shift=shift)

        if "\x40" <= last <= "\x5a" or "\x61" <= last <= "\x7a":
            parts = body[:-1].split(";", 1)
            mod = int(parts[1]) if len(parts) >= 2 and parts[1] else 1
            shift, alt, ctrl, _ = _decode_modifiers(mod)
            name = _CSI_LETTER.get(last)
            if name is None:
                return None
            if last == "Z":
                shift = True
                name = "tab"
            return ParsedKey(name=name, sequence=seq, ctrl=ctrl, meta=alt, shift=shift)
        return None

    if seq.startswith("\x1bO") and len(seq) == 3:
        name = _SS3_LETTER.get(seq[2])
        if name is None:
            return None
        return ParsedKey(name=name, sequence=seq)

    m = _META_RE.match(seq)
    if m:
        return ParsedKey(name=m.group(1), sequence=seq, meta=True)

    if len(seq) == 1:
        code = ord(seq)
        if seq == "\x1b":
            return ParsedKey(name="escape", sequence=seq)
        if seq in ("\r", "\n"):
            return ParsedKey(name="enter", sequence=seq)
        if seq == "\t":
            return ParsedKey(name="tab", sequence=seq)
        if seq == "\x7f":
            return ParsedKey(name="backspace", sequence=seq)
        if seq == " ":
            return ParsedKey(name="space", sequence=seq)
        if 1 <= code <= 31:
            name = _CTRL_CODES.get(code, chr(code + 96))
            return ParsedKey(name=name, sequence=seq, ctrl=True)
        return ParsedKey(name=seq, sequence=seq)

    return None
