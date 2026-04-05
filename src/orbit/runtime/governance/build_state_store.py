from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from orbit.models.core import new_id
from orbit.runtime.governance.protocol.builds import (
    ACTIVATION_POINTER_PATH,
    BuildManifest,
    ActivationPointer,
    build_manifest_path,
)
from orbit.runtime.governance.protocol.mode import RuntimeMode
from orbit.settings import DEFAULT_STATE_DIR, REPO_ROOT


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


class BuildStateStore:
    def __init__(self, *, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        self.state_dir = state_dir

    @property
    def activation_pointer_path(self) -> Path:
        return self.state_dir / "activation.json"

    def ensure_layout(self) -> None:
        (self.state_dir / "builds").mkdir(parents=True, exist_ok=True)

    def save_manifest(self, manifest: BuildManifest) -> Path:
        self.ensure_layout()
        path = build_manifest_path(manifest.build_id, state_dir=self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_manifest(self, build_id: str) -> BuildManifest | None:
        path = build_manifest_path(build_id, state_dir=self.state_dir)
        if not path.exists():
            return None
        return BuildManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def save_activation_pointer(self, pointer: ActivationPointer) -> Path:
        self.ensure_layout()
        path = self.activation_pointer_path
        path.write_text(pointer.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_activation_pointer(self) -> ActivationPointer:
        path = self.activation_pointer_path
        if not path.exists():
            return ActivationPointer()
        return ActivationPointer.model_validate_json(path.read_text(encoding="utf-8"))

    def create_candidate_build_record(self, *, runtime_mode: RuntimeMode, repo_root: Path = REPO_ROOT) -> BuildManifest:
        source_ref = _git_output(repo_root, "rev-parse", "HEAD")
        dirty_output = _git_output(repo_root, "status", "--porcelain")
        manifest = BuildManifest(
            build_id=new_id("build"),
            source_ref=source_ref,
            source_dirty=bool(dirty_output),
            runtime_mode_context=runtime_mode,
            validation_status="pending",
            activation_status="candidate",
        )
        self.save_manifest(manifest)
        pointer = self.load_activation_pointer()
        pointer.candidate_build_id = manifest.build_id
        self.save_activation_pointer(pointer)
        return manifest

    def materialize_candidate_build(self, *, runtime_mode: RuntimeMode, repo_root: Path = REPO_ROOT, python_executable: str | None = None) -> BuildManifest:
        manifest = self.create_candidate_build_record(runtime_mode=runtime_mode, repo_root=repo_root)
        build_root = self.state_dir / "builds" / manifest.build_id
        snapshot_root = build_root / "snapshot"
        shutil.copytree(repo_root, snapshot_root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git', '.orbit', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '*.pyc', 'node_modules'))

        manifest.python_executable = python_executable or os.getenv('ORBIT_BUILD_PYTHON') or os.sys.executable
        manifest.snapshot_root = str(snapshot_root)
        manifest.launch_command = self.stable_launch_command_for_manifest(manifest)
        self.save_manifest(manifest)
        return manifest

    def stable_launch_command_for_manifest(self, manifest: BuildManifest) -> list[str]:
        if not manifest.python_executable:
            raise ValueError("manifest has no python_executable")
        if not manifest.snapshot_root:
            raise ValueError("manifest has no snapshot_root")
        snapshot_root = Path(manifest.snapshot_root)
        return [
            manifest.python_executable,
            str(snapshot_root / 'apps' / 'orbit_cli.py'),
            '--mode',
            manifest.runtime_mode_context,
        ]

    def stable_launch_command_for_build(self, build_id: str) -> list[str]:
        manifest = self.load_manifest(build_id)
        if manifest is None:
            raise FileNotFoundError(f"build manifest not found for {build_id}")
        return self.stable_launch_command_for_manifest(manifest)

    def launch_build(self, build_id: str, *, extra_args: list[str] | None = None) -> subprocess.Popen[str]:
        command = self.stable_launch_command_for_build(build_id)
        if extra_args:
            command = [*command, *extra_args]
        return subprocess.Popen(command, text=True)

    def active_launch_command(self) -> list[str]:
        pointer = self.load_activation_pointer()
        if not pointer.active_build_id:
            raise FileNotFoundError("no active build configured")
        return self.stable_launch_command_for_build(pointer.active_build_id)

    def launch_active_build(self, *, extra_args: list[str] | None = None) -> subprocess.Popen[str]:
        command = self.active_launch_command()
        if extra_args:
            command = [*command, *extra_args]
        return subprocess.Popen(command, text=True)

    def promote_candidate_to_active(self) -> ActivationPointer:
        pointer = self.load_activation_pointer()
        if not pointer.candidate_build_id:
            raise FileNotFoundError("no candidate build configured")

        candidate_manifest = self.load_manifest(pointer.candidate_build_id)
        if candidate_manifest is None:
            raise FileNotFoundError(f"candidate build manifest not found for {pointer.candidate_build_id}")

        previous_active_id = pointer.active_build_id
        if previous_active_id:
            previous_active_manifest = self.load_manifest(previous_active_id)
            if previous_active_manifest is not None:
                previous_active_manifest.activation_status = "last_known_good"
                self.save_manifest(previous_active_manifest)
            pointer.last_known_good_build_id = previous_active_id

        candidate_manifest.activation_status = "active"
        self.save_manifest(candidate_manifest)

        pointer.active_build_id = candidate_manifest.build_id
        pointer.candidate_build_id = None
        self.save_activation_pointer(pointer)
        return pointer
