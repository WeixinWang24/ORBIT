from __future__ import annotations

import os
import subprocess
from pathlib import Path

from orbit.models.core import new_id
from orbit.runtime.governance.protocol.builds import (
    BuildManifest,
    ActivationPointer,
    build_manifest_path,
)
from orbit.runtime.governance.protocol.mode import RuntimeMode
from orbit.settings import DEFAULT_STATE_DIR, REPO_ROOT


LAUNCHER_TEMPLATE = '''from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

BUILD_ID = {build_id!r}
RUNTIME_ROOT = Path({runtime_root!r}).resolve()
SOURCE_REF = {source_ref!r}


def _normalize(path: str) -> str:
    return str(Path(path).resolve())


def main() -> None:
    if not RUNTIME_ROOT.exists():
        raise SystemExit(f"runtime_root missing for build {{BUILD_ID}}: {{RUNTIME_ROOT}}")

    runtime_root_str = _normalize(str(RUNTIME_ROOT))
    existing = []
    for item in sys.path:
        try:
            if _normalize(item) == runtime_root_str:
                continue
        except Exception:
            pass
        existing.append(item)
    sys.path[:] = [runtime_root_str, *existing]

    os.environ.setdefault("ORBIT_ACTIVE_BUILD_ID", BUILD_ID)
    os.environ.setdefault("ORBIT_ACTIVE_RUNTIME_ROOT", runtime_root_str)
    os.environ.setdefault("ORBIT_ACTIVE_SOURCE_REF", SOURCE_REF or "")

    import orbit  # noqa: PLC0415

    origin = Path(getattr(orbit, "__file__", "")).resolve()
    try:
        origin.relative_to(RUNTIME_ROOT)
    except Exception as exc:
        raise SystemExit(
            f"active build provenance check failed for build {{BUILD_ID}}: "
            f"orbit imported from {{origin}}, expected under {{RUNTIME_ROOT}}"
        ) from exc

    runpy.run_path(str(RUNTIME_ROOT / "apps" / "orbit_cli.py"), run_name="__main__")


if __name__ == "__main__":
    main()
'''


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

    def _prepare_build_layout(self, build_id: str) -> dict[str, Path]:
        build_root = self.state_dir / "builds" / build_id
        dist_root = build_root / "dist"
        runtime_root = build_root / "runtime"
        artifacts_root = build_root / "artifacts"
        launcher_path = build_root / "launch_active.py"
        for path in (build_root, dist_root, runtime_root, artifacts_root):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "build_root": build_root,
            "dist_root": dist_root,
            "runtime_root": runtime_root,
            "artifacts_root": artifacts_root,
            "launcher_path": launcher_path,
        }

    def _capture_build_provenance(self, *, repo_root: Path, build_root: Path, active_build_id: str | None) -> dict:
        source_ref = _git_output(repo_root, "rev-parse", "HEAD")
        dirty_output = _git_output(repo_root, "status", "--porcelain") or ""
        diff_summary = _git_output(repo_root, "diff", "--stat", "HEAD") or None
        patch_path: str | None = None
        if dirty_output:
            patch_text = _git_output(repo_root, "diff", "HEAD") or ""
            if patch_text:
                patch_file = build_root / "source.patch"
                patch_file.write_text(patch_text, encoding="utf-8")
                patch_path = str(patch_file)
        return {
            "source_ref": source_ref,
            "source_dirty": bool(dirty_output),
            "source_diff_summary": diff_summary,
            "source_patch_path": patch_path,
            "repo_root_at_build": str(repo_root.resolve()),
            "build_input_kind": "repo_tree",
            "parent_build_id": active_build_id,
        }

    def _build_candidate_wheel(self, *, repo_root: Path, dist_root: Path, python_executable: str) -> Path:
        completed = subprocess.run(
            [python_executable, "-m", "build", "--wheel", "--outdir", str(dist_root)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            details = completed.stderr or completed.stdout
            if "No module named build" in details:
                raise RuntimeError(
                    "wheel build failed: Python environment is missing the 'build' package. "
                    "Install it in the active Conda environment (for example: python -m pip install build)."
                )
            raise RuntimeError(f"wheel build failed: {details}")
        wheels = sorted(dist_root.glob("*.whl"))
        if not wheels:
            raise RuntimeError("wheel build completed but produced no .whl artifact")
        return wheels[-1]

    def _install_candidate_runtime(self, *, wheel_path: Path, runtime_root: Path, python_executable: str) -> Path:
        completed = subprocess.run(
            [python_executable, "-m", "pip", "install", "--no-deps", "--target", str(runtime_root), str(wheel_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"candidate runtime install failed: {completed.stderr or completed.stdout}")
        orbit_pkg = runtime_root / "orbit"
        if not orbit_pkg.exists():
            raise RuntimeError(f"candidate runtime install missing orbit package in {runtime_root}")
        apps_dir = runtime_root / "apps"
        apps_dir.mkdir(parents=True, exist_ok=True)
        source_cli = REPO_ROOT / "apps" / "orbit_cli.py"
        target_cli = apps_dir / "orbit_cli.py"
        target_cli.write_text(source_cli.read_text(encoding="utf-8"), encoding="utf-8")
        return runtime_root

    def _write_build_launcher(self, *, launcher_path: Path, build_id: str, runtime_root: Path, source_ref: str | None) -> Path:
        launcher_path.write_text(
            LAUNCHER_TEMPLATE.format(
                build_id=build_id,
                runtime_root=str(runtime_root),
                source_ref=source_ref,
            ),
            encoding="utf-8",
        )
        return launcher_path

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
        pointer = self.load_activation_pointer()
        effective_python = python_executable or os.getenv("ORBIT_BUILD_PYTHON") or os.sys.executable
        layout = self._prepare_build_layout(manifest.build_id)
        provenance = self._capture_build_provenance(
            repo_root=repo_root,
            build_root=layout["build_root"],
            active_build_id=pointer.active_build_id,
        )
        wheel_path = self._build_candidate_wheel(
            repo_root=repo_root,
            dist_root=layout["dist_root"],
            python_executable=effective_python,
        )
        runtime_root = self._install_candidate_runtime(
            wheel_path=wheel_path,
            runtime_root=layout["runtime_root"],
            python_executable=effective_python,
        )
        launcher_path = self._write_build_launcher(
            launcher_path=layout["launcher_path"],
            build_id=manifest.build_id,
            runtime_root=runtime_root,
            source_ref=provenance["source_ref"],
        )

        manifest.python_executable = effective_python
        manifest.wheel_path = str(wheel_path)
        manifest.runtime_root = str(runtime_root)
        manifest.launcher_path = str(launcher_path)
        manifest.launch_command = self.stable_launch_command_for_manifest(manifest)
        manifest.parent_build_id = provenance["parent_build_id"]
        manifest.source_ref = provenance["source_ref"]
        manifest.source_dirty = provenance["source_dirty"]
        manifest.source_diff_summary = provenance["source_diff_summary"]
        manifest.source_patch_path = provenance["source_patch_path"]
        manifest.repo_root_at_build = provenance["repo_root_at_build"]
        manifest.build_input_kind = provenance["build_input_kind"]
        self.save_manifest(manifest)
        return manifest

    def stable_launch_command_for_manifest(self, manifest: BuildManifest) -> list[str]:
        if not manifest.python_executable:
            raise ValueError("manifest has no python_executable")
        if not manifest.launcher_path:
            raise ValueError("manifest has no launcher_path")
        return [
            manifest.python_executable,
            manifest.launcher_path,
            "--mode",
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
