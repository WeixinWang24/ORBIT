"""Python entrypoint for the ORBIT mock PTY workbench.

Run from the ORBIT project directory with the Conda `Orbit` environment active.
Example:
    python3 apps/orbit_workbench.py
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
