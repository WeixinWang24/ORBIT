"""Backward-compatible persistence import for early ORBIT scaffolding.

This module is intentionally kept as a compatibility shim so existing imports
that still reference `orbit.db` do not immediately break while the codebase is
moving to the explicit store abstraction.

New code should prefer imports from `orbit.store`.
"""

from orbit.store.sqlite_store import SQLiteStore as OrbitDB

__all__ = ["OrbitDB"]
