"""Python entrypoint for the ORBIT raw PTY workbench.

Run from the ORBIT project directory with the Conda `Orbit` environment active.
Example:
    python3 apps/orbit_workbench_raw.py

Optional diagnostics:
    ORBIT_PTY_DEBUG=1 python3 apps/orbit_workbench_raw.py

Current key rule:
    q or Ctrl-C exit; Esc is reserved for ignore/back behavior, not global exit.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orbit.interfaces.pty_workbench import browse


if __name__ == "__main__":
    browse()
