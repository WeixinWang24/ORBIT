from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from orbit.runtime.governance.build_state_store import BuildStateStore
from orbit.runtime.governance.protocol.builds import ActivationPointer, BuildManifest


class ActiveBuildLauncherScriptTests(unittest.TestCase):
    def test_print_active_launch_outputs_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / '.orbit'
            state_dir.mkdir(parents=True, exist_ok=True)
            store = BuildStateStore(state_dir=state_dir)
            store.save_manifest(BuildManifest(build_id='build-active', runtime_mode_context='evo', python_executable='/tmp/active-python', launcher_path='/tmp/build-active/launch_active.py'))
            store.save_activation_pointer(ActivationPointer(active_build_id='build-active'))

            completed = subprocess.run(
                [sys.executable, 'apps/orbit_print_active_launch.py'],
                cwd='/Volumes/2TB/MAS/openclaw-core/ORBIT',
                env={**dict(), 'PYTHONPATH': '/Volumes/2TB/MAS/openclaw-core/ORBIT/src', 'ORBIT_STATE_DIR': str(state_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertIn('/tmp/active-python', completed.stdout)
            self.assertIn('/tmp/build-active/launch_active.py', completed.stdout)
            self.assertIn('--mode evo', completed.stdout)


if __name__ == '__main__':
    unittest.main()
