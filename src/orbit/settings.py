"""Repository-local settings for ORBIT.

These settings intentionally stay simple in the current scaffold. They provide
stable local defaults while allowing later configuration growth when the
runtime, notebook, and PostgreSQL-backed persistence become more mature.
"""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIR = Path(os.getenv("ORBIT_STATE_DIR", str(REPO_ROOT / ".orbit")))
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
DEFAULT_MEMORY_EMBEDDING_MODEL = os.getenv("ORBIT_MEMORY_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_MEMORY_RETRIEVAL_TOP_K = int(os.getenv("ORBIT_MEMORY_RETRIEVAL_TOP_K", "5"))
DEFAULT_MEMORY_RETRIEVAL_SEMANTIC_WEIGHT = float(os.getenv("ORBIT_MEMORY_RETRIEVAL_SEMANTIC_WEIGHT", "0.8"))
DEFAULT_MEMORY_RETRIEVAL_LEXICAL_WEIGHT = float(os.getenv("ORBIT_MEMORY_RETRIEVAL_LEXICAL_WEIGHT", "0.2"))
DEFAULT_MEMORY_RETRIEVAL_DURABLE_BOOST = float(os.getenv("ORBIT_MEMORY_RETRIEVAL_DURABLE_BOOST", "0.05"))
DEFAULT_MEMORY_RETRIEVAL_SESSION_BOOST = float(os.getenv("ORBIT_MEMORY_RETRIEVAL_SESSION_BOOST", "0.0"))
DEFAULT_MEMORY_RETRIEVAL_SALIENCE_WEIGHT = float(os.getenv("ORBIT_MEMORY_RETRIEVAL_SALIENCE_WEIGHT", "0.05"))
DEFAULT_INSPECTOR_HOST = os.getenv("ORBIT_INSPECTOR_HOST", "127.0.0.1")
DEFAULT_INSPECTOR_PORT = int(os.getenv("ORBIT_INSPECTOR_PORT", "8789"))
