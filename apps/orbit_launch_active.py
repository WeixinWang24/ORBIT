"""Launch the currently active materialized ORBIT build."""

from __future__ import annotations

import os
import subprocess
import sys

from orbit.runtime.governance.build_state_store import BuildStateStore


def main() -> None:
    store = BuildStateStore()
    command = store.active_launch_command()
    if len(sys.argv) > 1:
        command = [*command, *sys.argv[1:]]
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
