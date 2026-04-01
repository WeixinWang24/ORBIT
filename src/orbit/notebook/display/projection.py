"""Notebook-friendly projection helpers for ORBIT runtime artifacts.

These helpers intentionally project persisted runtime state into plain Python
structures so notebooks can inspect the system without owning a parallel domain
model.
"""

from __future__ import annotations

from orbit.store.base import OrbitStore


def project_run(store: OrbitStore, run_id: str) -> dict:
    """Project a run and its related artifacts into notebook-friendly data.

    The returned structure is intentionally simple so it can be rendered as raw
    JSON, tables, or custom notebook cells without changing the underlying
    runtime object model.
    """
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    return {
        "run": run.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in store.list_steps_for_run(run_id)],
        "events": [event.model_dump(mode="json") for event in store.list_events_for_run(run_id)],
        "context_artifacts": [artifact.model_dump(mode="json") for artifact in store.list_context_for_run(run_id)],
    }
