from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from orbit.runtime.governance.build_state_store import BuildStateStore
from orbit.runtime.governance.protocol.builds import ActivationPointer, BuildManifest


class BuildStateStoreTests(unittest.TestCase):
    def test_activation_pointer_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            pointer = store.load_activation_pointer()

            self.assertIsNone(pointer.active_build_id)
            self.assertIsNone(pointer.candidate_build_id)
            self.assertIsNone(pointer.last_known_good_build_id)
            self.assertEqual(pointer.schema_version, "v1")

    def test_save_and_load_build_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            manifest = BuildManifest(
                build_id="build-001",
                source_ref="abc123",
                source_dirty=False,
                runtime_mode_context="evo",
                validation_status="passed",
                activation_status="candidate",
                python_executable="/tmp/orbit-python",
                snapshot_root="/tmp/build-001/snapshot",
            )
            path = store.save_manifest(manifest)
            loaded = store.load_manifest("build-001")

            self.assertTrue(path.exists())
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.build_id, "build-001")
            self.assertEqual(loaded.source_ref, "abc123")
            self.assertEqual(loaded.runtime_mode_context, "evo")
            self.assertEqual(loaded.validation_status, "passed")
            self.assertEqual(loaded.python_executable, "/tmp/orbit-python")
            self.assertEqual(loaded.snapshot_root, "/tmp/build-001/snapshot")

    def test_save_and_load_activation_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            pointer = ActivationPointer(
                active_build_id="build-002",
                candidate_build_id="build-003",
                last_known_good_build_id="build-001",
            )
            path = store.save_activation_pointer(pointer)
            loaded = store.load_activation_pointer()

            self.assertTrue(path.exists())
            self.assertEqual(loaded.active_build_id, "build-002")
            self.assertEqual(loaded.candidate_build_id, "build-003")
            self.assertEqual(loaded.last_known_good_build_id, "build-001")

    def test_create_candidate_build_record_updates_manifest_and_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo_root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo_root, check=True, capture_output=True)
            (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo_root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True)

            store = BuildStateStore(state_dir=repo_root / ".orbit-test")
            manifest = store.create_candidate_build_record(runtime_mode="evo", repo_root=repo_root)
            loaded_manifest = store.load_manifest(manifest.build_id)
            pointer = store.load_activation_pointer()

            self.assertIsNotNone(loaded_manifest)
            assert loaded_manifest is not None
            self.assertEqual(loaded_manifest.build_id, manifest.build_id)
            self.assertEqual(loaded_manifest.runtime_mode_context, "evo")
            self.assertEqual(loaded_manifest.activation_status, "candidate")
            self.assertFalse(loaded_manifest.source_dirty)
            self.assertIsNotNone(loaded_manifest.source_ref)
            self.assertEqual(pointer.candidate_build_id, manifest.build_id)

    def test_materialize_candidate_build_sets_launch_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path('/Volumes/2TB/MAS/openclaw-core/ORBIT')
            store = BuildStateStore(state_dir=Path(tmpdir))
            manifest = store.materialize_candidate_build(runtime_mode='evo', repo_root=repo_root)
            loaded = store.load_manifest(manifest.build_id)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.runtime_mode_context, 'evo')
            self.assertEqual(loaded.environment_kind, 'host_conda_bound')
            self.assertTrue(Path(loaded.snapshot_root).exists())
            self.assertTrue(Path(loaded.snapshot_root, 'apps', 'orbit_cli.py').exists())
            self.assertTrue(loaded.python_executable)
            self.assertTrue(loaded.launch_command)
            self.assertEqual(loaded.launch_command[-2:], ['--mode', 'evo'])
            self.assertTrue(loaded.launch_command[1].endswith('apps/orbit_cli.py'))
            pointer = store.load_activation_pointer()
            self.assertEqual(pointer.candidate_build_id, loaded.build_id)

    def test_stable_launch_command_for_manifest_includes_runtime_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            manifest = BuildManifest(build_id='build-xyz', runtime_mode_context='evo', python_executable='/tmp/fake-python', snapshot_root='/tmp/fake-snapshot')
            command = store.stable_launch_command_for_manifest(manifest)
            self.assertEqual(command[-2:], ['--mode', 'evo'])
            self.assertEqual(command[:2], ['/tmp/fake-python', '/tmp/fake-snapshot/apps/orbit_cli.py'])

    def test_stable_launch_command_for_build_reads_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            manifest = BuildManifest(build_id='build-abc', runtime_mode_context='dev', python_executable='/tmp/stable-python', snapshot_root='/tmp/stable-snapshot')
            store.save_manifest(manifest)
            command = store.stable_launch_command_for_build('build-abc')
            self.assertEqual(command[-2:], ['--mode', 'dev'])
            self.assertEqual(command[:2], ['/tmp/stable-python', '/tmp/stable-snapshot/apps/orbit_cli.py'])

    def test_stable_launch_command_for_build_raises_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            with self.assertRaises(FileNotFoundError):
                store.stable_launch_command_for_build('missing-build')

    def test_active_launch_command_reads_active_build_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            manifest = BuildManifest(build_id='build-active', runtime_mode_context='evo', python_executable='/tmp/active-python', snapshot_root='/tmp/active-snapshot')
            store.save_manifest(manifest)
            store.save_activation_pointer(ActivationPointer(active_build_id='build-active'))
            command = store.active_launch_command()
            self.assertEqual(command[:2], ['/tmp/active-python', '/tmp/active-snapshot/apps/orbit_cli.py'])
            self.assertEqual(command[-2:], ['--mode', 'evo'])

    def test_active_launch_command_raises_when_no_active_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            with self.assertRaises(FileNotFoundError):
                store.active_launch_command()

    def test_promote_candidate_to_active_moves_previous_active_to_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            old_active = BuildManifest(build_id='build-old', runtime_mode_context='dev', python_executable='/tmp/old-python', snapshot_root='/tmp/old-snapshot', activation_status='active')
            candidate = BuildManifest(build_id='build-new', runtime_mode_context='evo', python_executable='/tmp/new-python', snapshot_root='/tmp/new-snapshot', activation_status='candidate')
            store.save_manifest(old_active)
            store.save_manifest(candidate)
            store.save_activation_pointer(ActivationPointer(active_build_id='build-old', candidate_build_id='build-new'))

            pointer = store.promote_candidate_to_active()
            new_manifest = store.load_manifest('build-new')
            old_manifest = store.load_manifest('build-old')

            self.assertEqual(pointer.active_build_id, 'build-new')
            self.assertIsNone(pointer.candidate_build_id)
            self.assertEqual(pointer.last_known_good_build_id, 'build-old')
            assert new_manifest is not None and old_manifest is not None
            self.assertEqual(new_manifest.activation_status, 'active')
            self.assertEqual(old_manifest.activation_status, 'last_known_good')

    def test_promote_candidate_to_active_raises_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BuildStateStore(state_dir=Path(tmpdir))
            with self.assertRaises(FileNotFoundError):
                store.promote_candidate_to_active()


if __name__ == "__main__":
    unittest.main()
