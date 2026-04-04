"""Python entrypoint for the ORBIT prompt-toolkit mock workbench.

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

from orbit.interfaces.ptk_workbench import run_workbench


if __name__ == "__main__":
    run_workbench()
