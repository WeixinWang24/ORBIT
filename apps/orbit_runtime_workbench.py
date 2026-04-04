"""Python entrypoint for the runtime-first raw PTY ORBIT workbench.

This entrypoint intentionally does NOT replace the reference raw PTY shell.
Use it to evaluate the newer runtime-first CLI while keeping
`apps/orbit_workbench_raw.py` pointed at the reference `pty_workbench.py`.

Run from the ORBIT project directory with the Conda `Orbit` environment active.
Example:
    python3 apps/orbit_runtime_workbench.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orbit.interfaces.pty_runtime_cli import browse_runtime_cli


if __name__ == "__main__":
    browse_runtime_cli()
