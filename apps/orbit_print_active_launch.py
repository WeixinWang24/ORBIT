"""Print the launch command for the currently active materialized ORBIT build."""

from __future__ import annotations

import shlex

from orbit.runtime.governance.build_state_store import BuildStateStore


def main() -> None:
    store = BuildStateStore()
    command = store.active_launch_command()
    print(" ".join(shlex.quote(part) for part in command))


if __name__ == "__main__":
    main()
