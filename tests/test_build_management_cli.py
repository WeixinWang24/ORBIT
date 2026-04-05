from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from orbit.runtime.governance.build_state_store import BuildStateStore
from orbit.runtime.governance.protocol.builds import ActivationPointer, BuildManifest


class BuildManagementCliTests(unittest.TestCase):
    def test_print_active_launch_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / '.orbit'
            state_dir.mkdir(parents=True, exist_ok=True)
            store = BuildStateStore(state_dir=state_dir)
            store.save_manifest(BuildManifest(build_id='build-active', runtime_mode_context='evo', venv_path='/tmp/active-venv'))
            store.save_activation_pointer(ActivationPointer(active_build_id='build-active'))

            completed = subprocess.run(
                [sys.executable, 'apps/orbit_build_cli.py', 'print-active-launch'],
                cwd='/Volumes/2TB/MAS/openclaw-core/ORBIT',
                env={'PYTHONPATH': '/Volumes/2TB/MAS/openclaw-core/ORBIT/src', 'ORBIT_STATE_DIR': str(state_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertIn('/tmp/active-venv/bin/python', completed.stdout)
            self.assertIn('--mode evo', completed.stdout)

    def test_promote_candidate_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / '.orbit'
            state_dir.mkdir(parents=True, exist_ok=True)
            store = BuildStateStore(state_dir=state_dir)
            store.save_manifest(BuildManifest(build_id='build-old', runtime_mode_context='dev', venv_path='/tmp/old-venv', activation_status='active'))
            store.save_manifest(BuildManifest(build_id='build-new', runtime_mode_context='evo', venv_path='/tmp/new-venv', activation_status='candidate'))
            store.save_activation_pointer(ActivationPointer(active_build_id='build-old', candidate_build_id='build-new'))

            completed = subprocess.run(
                [sys.executable, 'apps/orbit_build_cli.py', 'promote-candidate'],
                cwd='/Volumes/2TB/MAS/openclaw-core/ORBIT',
                env={'PYTHONPATH': '/Volumes/2TB/MAS/openclaw-core/ORBIT/src', 'ORBIT_STATE_DIR': str(state_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload['active_build_id'], 'build-new')
            self.assertEqual(payload['last_known_good_build_id'], 'build-old')


if __name__ == '__main__':
    unittest.main()
