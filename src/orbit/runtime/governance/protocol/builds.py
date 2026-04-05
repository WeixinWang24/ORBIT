from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from orbit.models.core import OrbitBaseModel
from orbit.runtime.governance.protocol.mode import RuntimeMode
from orbit.settings import DEFAULT_STATE_DIR

BuildValidationStatus = Literal["pending", "passed", "failed", "unknown"]
BuildActivationStatus = Literal["candidate", "active", "last_known_good", "inactive", "unknown"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


BUILDS_STATE_DIR = DEFAULT_STATE_DIR / "builds"
ACTIVATION_POINTER_PATH = DEFAULT_STATE_DIR / "activation.json"


class BuildManifest(OrbitBaseModel):
    schema_version: str = "v1"
    build_id: str
    generated_at: datetime = Field(default_factory=_utc_now)
    source_ref: str | None = None
    source_dirty: bool = True
    source_diff_summary: str | None = None
    runtime_mode_context: RuntimeMode = "dev"
    validation_status: BuildValidationStatus = "pending"
    activation_status: BuildActivationStatus = "inactive"
    environment_kind: str = "host_conda_bound"
    python_executable: str | None = None
    snapshot_root: str | None = None
    launch_command: list[str] = Field(default_factory=list)
    parent_build_id: str | None = None


class ActivationPointer(OrbitBaseModel):
    schema_version: str = "v1"
    active_build_id: str | None = None
    candidate_build_id: str | None = None
    last_known_good_build_id: str | None = None
    updated_at: datetime = Field(default_factory=_utc_now)


def build_manifest_path(build_id: str, *, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    return state_dir / "builds" / build_id / "manifest.json"
