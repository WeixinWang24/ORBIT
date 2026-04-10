"""Thin application entrypoint wrapper for the runtime-first ORBIT CLI."""

from __future__ import annotations

import argparse
import time

from orbit.runtime.project_env import load_env_local

PROGRAM_IMPORT_STARTED_AT = time.perf_counter()

load_env_local(override=True)


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
