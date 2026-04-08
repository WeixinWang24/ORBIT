from __future__ import annotations

import datetime
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

# Allowlist of acceptable shell interpreters. The SHELL env var is validated against
# this list to prevent indirect execution-semantics changes via environment injection.
_SHELL_ALLOWLIST = frozenset({
    "/bin/sh",
    "/bin/bash",
    "/usr/bin/bash",
    "/usr/bin/sh",
    "/bin/zsh",
    "/usr/bin/zsh",
    "/usr/local/bin/bash",
    "/usr/local/bin/zsh",
})
_SHELL_FALLBACK = "/bin/sh"


def _resolve_shell() -> str:
    candidate = os.environ.get("SHELL", "").strip()
    if candidate in _SHELL_ALLOWLIST:
        return candidate
    return _SHELL_FALLBACK


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    """
    Atomically write the runner status file using a temp-file + os.replace pattern.
    This prevents concurrent readers from observing a partially-written file.

    This file is the PRIMARY source of terminal lifecycle truth for the ProcessService.
    It must be written before the runner exits so any later service instance can recover
    terminal state without relying on pid polling or in-memory handles.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    full_payload = {**payload, "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(full_payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: managed_process_runner.py <status_path> <stdout_path> <stderr_path> <command>", file=sys.stderr)
        return 2

    status_path = Path(sys.argv[1]).resolve()
    stdout_path = Path(sys.argv[2]).resolve()
    stderr_path = Path(sys.argv[3]).resolve()
    command = sys.argv[4]
    shell = _resolve_shell()

    state: dict[str, Any] = {
        "status": "running",
        "exit_code": None,
        "signal": None,
    }

    def _handle_signal(signum, frame):  # type: ignore[no-untyped-def]
        state["status"] = "killed"
        state["signal"] = signum
        # Write terminal truth immediately before exiting so that any waiting
        # ProcessService instance can confirm termination via the status file.
        # AUD-NEW-001: protect _write_status with try/except so that a write failure
        # (e.g., disk full) does not silently cancel SystemExit — the runner must always
        # exit when it receives SIGTERM. The service recovery path handles a missing file.
        try:
            _write_status(status_path, state)
        except Exception as exc:
            # Write failure (e.g., disk full) must not prevent exit on SIGTERM.
            # Log to stderr so the failure is visible in the captured stderr file
            # even though the status file was not written. The service recovery path
            # (_write_recovery_status_file) will attempt to fill in terminal truth.
            print(f"runner: failed to write terminal status: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    # Write initial running status. The ProcessService uses the presence of this file
    # as confirmation that the runner has started and registered its signal handlers
    # (see _wait_for_runner_startup in service.py).
    _write_status(status_path, state)

    with open(stdout_path, "a", encoding="utf-8") as stdout_file, open(stderr_path, "a", encoding="utf-8") as stderr_file:
        completed = subprocess.run(
            [shell, "-lc", command],
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

    state["exit_code"] = completed.returncode
    if state.get("status") != "killed":
        state["status"] = "completed" if completed.returncode == 0 else "failed"
    # Write final terminal truth. This write is the primary lifecycle signal read
    # by ProcessService.refresh_process and _wait_for_runner_terminal.
    _write_status(status_path, state)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
