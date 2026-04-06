from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from orbit.models.core import OrbitBaseModel
from orbit.settings import DEFAULT_WORKSPACE_ROOT, REPO_ROOT


RuntimeMode = Literal["dev", "evo"]


class ModePolicyDescriptor(OrbitBaseModel):
    mode_policy_profile: str = "dev-default"
    self_runtime_visibility: str = "workspace_only"
    self_modification_posture: str = "not_enabled"


def workspace_root_for_runtime_mode(runtime_mode: RuntimeMode) -> Path:
    return REPO_ROOT if runtime_mode == "evo" else DEFAULT_WORKSPACE_ROOT


def mode_policy_summary(runtime_mode: RuntimeMode) -> dict[str, str]:
    if runtime_mode == "evo":
        return {
            "mode_policy_profile": "evo-phase-a",
            "self_runtime_visibility": "repo_root",
            "self_modification_posture": "phase_a_read_heavy",
        }
    return {
        "mode_policy_profile": "dev-default",
        "self_runtime_visibility": "workspace_only",
        "self_modification_posture": "not_enabled",
    }


def build_policy_profile_for_mode(runtime_mode: RuntimeMode) -> str:
    """Return the build policy profile string for the given runtime mode."""
    return "evo-phase-a-build" if runtime_mode == "evo" else "none"


def build_mode_policy_snapshot(*, runtime_mode: RuntimeMode, workspace_root: str) -> dict[str, str]:
    payload = dict(mode_policy_summary(runtime_mode))
    payload["workspace_root"] = workspace_root
    return payload
