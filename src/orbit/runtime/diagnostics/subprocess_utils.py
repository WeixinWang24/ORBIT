from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _coerce_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_bounded_subprocess(
    *,
    cmd: list[str],
    cwd: Path,
    timeout_seconds: float,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "timed_out": True,
            "stdout": _coerce_output_text(exc.stdout),
            "stderr": _coerce_output_text(exc.stderr),
        }
