"""Repository-local settings for ORBIT.

These settings intentionally stay simple in the current scaffold. They provide
stable local defaults while allowing later configuration growth when the
runtime, notebook, and PostgreSQL-backed persistence become more mature.
"""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIR = REPO_ROOT / ".orbit"
DEFAULT_DB_PATH = DEFAULT_STATE_DIR / "orbit.db"
DEFAULT_WORKSPACE_ROOT = REPO_ROOT / "workspace"

# PostgreSQL is the intended primary persistence direction for ORBIT. These
# defaults support local development without forcing configuration machinery
# into the codebase too early.
DEFAULT_PG_HOST = os.getenv("ORBIT_PG_HOST", "127.0.0.1")
DEFAULT_PG_PORT = int(os.getenv("ORBIT_PG_PORT", "5432"))
DEFAULT_PG_DBNAME = os.getenv("ORBIT_PG_DBNAME", "orbit")
DEFAULT_PG_USER = os.getenv("ORBIT_PG_USER", "orbit")
DEFAULT_PG_PASSWORD = os.getenv("ORBIT_PG_PASSWORD", "orbit")
DEFAULT_STORE_BACKEND = os.getenv("ORBIT_STORE_BACKEND", "postgres")
