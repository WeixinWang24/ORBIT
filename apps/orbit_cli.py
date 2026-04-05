"""Thin application entrypoint wrapper for the runtime-first ORBIT CLI."""

from __future__ import annotations

import argparse

from orbit.interfaces.pty_runtime_cli import browse_runtime_cli


def main() -> None:
    parser = argparse.ArgumentParser(description="ORBIT runtime-first CLI")
    parser.add_argument(
        "--chat-history-limit",
        type=int,
        default=None,
        help="Maximum number of recent chat messages to render in chat mode (default: 20, env: ORBIT_CLI_CHAT_HISTORY_LIMIT)",
    )
    args = parser.parse_args()
    browse_runtime_cli(chat_history_limit=args.chat_history_limit)


if __name__ == "__main__":
    main()
