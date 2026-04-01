"""Compatibility entrypoint for ORBIT.

Canonical runnable wrapper now lives at `apps/orbit_cli.py`.
This file remains as a thin compatibility shim.
"""

from apps.orbit_cli import app


if __name__ == "__main__":
    app()
