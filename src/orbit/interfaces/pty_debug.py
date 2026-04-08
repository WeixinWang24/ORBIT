"""Minimal file-based debug logging for raw PTY workbench diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone

_DEBUG_ENABLED = os.environ.get("ORBIT_PTY_DEBUG", "").lower() in {"1", "true", "yes", "on"}
_DEBUG_PATH = Path(os.environ.get("ORBIT_PTY_DEBUG_LOG", str(Path(__file__).resolve().parents[3] / ".tmp" / "orbit_pty_debug.log")))


def debug_enabled() -> bool:
    return _DEBUG_ENABLED


def debug_log(message: str) -> None:
    if not _DEBUG_ENABLED:
        return
    _DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with _DEBUG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
