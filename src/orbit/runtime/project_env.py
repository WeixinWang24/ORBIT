from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_LOCAL = REPO_ROOT / ".env.local"


def load_env_local(*, override: bool = True) -> bool:
    """Parse and apply .env.local into os.environ if present.

    Accepts lines of the form:
        [export] KEY=VALUE
    Comments and blank lines are ignored. Matching outer quotes are stripped.
    Returns True when the file exists and was processed, False otherwise.
    """
    if not ENV_LOCAL.exists():
        return False
    try:
        text = ENV_LOCAL.read_text(encoding="utf-8")
    except OSError:
        return False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val
    return True


def get_obsidian_vault_root() -> str:
    """Return the configured Obsidian vault root after loading project-local env."""
    load_env_local(override=True)
    return os.environ.get("ORBIT_OBSIDIAN_VAULT_ROOT", "").strip()
