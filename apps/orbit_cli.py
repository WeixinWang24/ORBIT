"""Thin application entrypoint wrapper for the runtime-first ORBIT CLI."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

PROGRAM_IMPORT_STARTED_AT = time.perf_counter()

# Repo root is three levels up from apps/orbit_cli.py
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_LOCAL = _REPO_ROOT / ".env.local"


def _load_env_local() -> None:
    """Parse and apply .env.local into os.environ (if the file exists).

    Only processes lines of the form:
        [export] KEY=VALUE
    Comments (#) and blank lines are skipped.  Values may be optionally
    wrapped in single or double quotes.  .env.local is the authoritative
    machine config so its values always overwrite whatever is in os.environ.
    """
    if not _ENV_LOCAL.exists():
        return
    try:
        text = _ENV_LOCAL.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # Strip matching outer quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        os.environ[key] = val


_load_env_local()


def main() -> None:
    parser = argparse.ArgumentParser(description="ORBIT runtime-first CLI")
    parser.add_argument(
        "--chat-history-limit",
        type=int,
        default=None,
        help="Maximum number of recent chat messages to render in chat mode (default: 20, env: ORBIT_CLI_CHAT_HISTORY_LIMIT)",
    )
    parser.add_argument(
        "--mode",
        choices=["dev", "evo"],
        default="dev",
        help="Runtime mode for the ORBIT CLI (default: dev)",
    )
    args = parser.parse_args()
    import_started_before_cli = time.perf_counter()
    from orbit.interfaces.pty_runtime_cli import browse_runtime_cli
    cli_import_finished_at = time.perf_counter()
    app_started_at = cli_import_finished_at
    startup_metrics = {
        'python_import_to_main_ms': round((import_started_before_cli - PROGRAM_IMPORT_STARTED_AT) * 1000, 2),
        'pty_runtime_cli_import_ms': round((cli_import_finished_at - import_started_before_cli) * 1000, 2),
    }
    browse_runtime_cli(runtime_mode=args.mode, chat_history_limit=args.chat_history_limit, app_started_at=app_started_at, startup_metrics=startup_metrics)


if __name__ == "__main__":
    main()
