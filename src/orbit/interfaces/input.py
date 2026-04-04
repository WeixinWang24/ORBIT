"""Keyboard and mouse input parser for ORBIT PTY interface.

Tokenizer-first note:
- raw stdin should first be split into text tokens vs escape/control sequences
- chat composer should consume only text tokens
- escape/control sequences should stay on the functional path and never degrade
  into text input

This file keeps the existing sequence parser while adding a minimal tokenizer-
first slice for the PTY runtime CLI.
"""

from __future__ import annotations

import os
import re
import select
import sys
import fcntl
import termios
from dataclasses import dataclass

ESC = "\x1b"
_INPUT_DEBUG_ENABLED = os.environ.get("ORBIT_PTY_DEBUG", "").lower() in {"1", "true", "yes", "on"}
_INPUT_DEBUG_PATH = "/Volumes/2TB/MAS/openclaw-core/ORBIT/.tmp/orbit_pty_debug.log"
_INPUT_DEBUG_VERSION = "input_tokenizer_v1"
_PENDING_SEQ = ""
_PENDING_AGE = 0
_PENDING_MAX_AGE = 3

_TOKENIZER_BUFFER = ""
_TOKENIZER_STATE = "ground"


def _input_debug(message: str) -> None:
    if not _INPUT_DEBUG_ENABLED:
        return
    os.makedirs(os.path.dirname(_INPUT_DEBUG_PATH), exist_ok=True)
    with open(_INPUT_DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{_INPUT_DEBUG_VERSION}:{message}\n")


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


@dataclass
class TextToken:
    value: str


@dataclass
class SequenceToken:
    value: str


@dataclass
class ControlToken:
    value: str


InputEvent = ParsedKey | ParsedMouse | ParsedFocus
InputToken = TextToken | ControlToken | SequenceToken

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


def read_chunk(timeout_ms: float = 50.0) -> str:
    timeout_s = max(0.005, timeout_ms / 1000.0)
    fd = sys.stdin.fileno()
    r, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not r:
        return ""

    chunks: list[str] = []
    while True:
        try:
            available = max(1, fcntl.ioctl(fd, termios.FIONREAD, b"    ")[0])
        except Exception:
            available = 1
        try:
            piece = os.read(fd, available)
        except BlockingIOError:
            piece = b""
        if not piece:
            break
        try:
            chunks.append(piece.decode("utf-8", errors="ignore"))
        except Exception:
            chunks.append(piece.decode(errors="ignore"))
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            break
    return "".join(chunks)


def _is_esc_final(code: int) -> bool:
    return 0x30 <= code <= 0x7E


def _is_csi_param(code: int) -> bool:
    return 0x30 <= code <= 0x3F


def _is_csi_intermediate(code: int) -> bool:
    return 0x20 <= code <= 0x2F


def tokenize_input_chunk(chunk: str, *, flush: bool = False) -> list[InputToken]:
    global _TOKENIZER_BUFFER, _TOKENIZER_STATE
    data = _TOKENIZER_BUFFER + chunk
    tokens: list[InputToken] = []
    i = 0
    text_start = 0
    seq_start = 0
    state = _TOKENIZER_STATE

    def flush_text(end: int) -> None:
        nonlocal text_start
        if end > text_start:
            text = data[text_start:end]
            if text:
                current_text = []
                for ch in text:
                    code = ord(ch)
                    if ch in {"\r", "\n", "\t", "\x7f"} or (0 <= code < 32 and ch != "\x1b"):
                        if current_text:
                            tokens.append(TextToken("".join(current_text)))
                            current_text = []
                        tokens.append(ControlToken(ch))
                    else:
                        current_text.append(ch)
                if current_text:
                    tokens.append(TextToken("".join(current_text)))
        text_start = end

    def emit_sequence(end: int) -> None:
        nonlocal state, text_start
        seq = data[seq_start:end]
        if seq:
            tokens.append(SequenceToken(seq))
        state = "ground"
        text_start = end

    while i < len(data):
        code = ord(data[i])
        if state == "ground":
            if code == 0x1B:
                flush_text(i)
                seq_start = i
                state = "escape"
                i += 1
            else:
                i += 1
            continue

        if state == "escape":
            if i >= len(data):
                break
            if code == 0x5B:
                state = "csi"
                i += 1
            elif code == 0x4F:
                state = "ss3"
                i += 1
            elif code in (0x5D, 0x50, 0x5E, 0x5F):
                state = "string"
                i += 1
            elif _is_csi_intermediate(code):
                state = "escape_intermediate"
                i += 1
            elif _is_esc_final(code):
                i += 1
                emit_sequence(i)
            else:
                state = "ground"
                text_start = seq_start
            continue

        if state == "escape_intermediate":
            if i >= len(data):
                break
            if _is_csi_intermediate(code):
                i += 1
            elif _is_esc_final(code):
                i += 1
                emit_sequence(i)
            else:
                state = "ground"
                text_start = seq_start
            continue

        if state == "csi":
            if i >= len(data):
                break
            if 0x40 <= code <= 0x7E:
                i += 1
                emit_sequence(i)
            elif _is_csi_param(code) or _is_csi_intermediate(code):
                i += 1
            else:
                state = "ground"
                text_start = seq_start
            continue

        if state == "ss3":
            if i >= len(data):
                break
            if 0x40 <= code <= 0x7E:
                i += 1
                emit_sequence(i)
            else:
                state = "ground"
                text_start = seq_start
            continue

        if state == "string":
            if i >= len(data):
                break
            if code == 0x07:
                i += 1
                emit_sequence(i)
            elif code == 0x1B and i + 1 < len(data) and data[i + 1] == "\\":
                i += 2
                emit_sequence(i)
            else:
                i += 1
            continue

    if state == "ground":
        flush_text(len(data))
        _TOKENIZER_BUFFER = ""
    elif flush:
        remaining = data[seq_start:]
        if remaining:
            tokens.append(SequenceToken(remaining))
        _TOKENIZER_BUFFER = ""
        state = "ground"
    else:
        _TOKENIZER_BUFFER = data[seq_start:]

    _TOKENIZER_STATE = state
    return tokens


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
