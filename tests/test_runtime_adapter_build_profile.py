from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import build_codex_session_manager_for_profile
from orbit.interfaces.runtime_profile import resolve_runtime_profile


class RuntimeAdapterBuildProfileTests(unittest.TestCase):
    def test_build_codex_session_manager_records_profile_timings(self) -> None:
        manager, _composer, _bundle = build_codex_session_manager_for_profile(
            profile=resolve_runtime_profile('runtime_core_minimal', runtime_mode='evo')
        )
        timings = getattr(manager, 'metadata', {}).get('build_profile_timings', {})
        self.assertIn('workspace_select_ms', timings)
        self.assertIn('backend_init_ms', timings)
        self.assertIn('session_manager_init_ms', timings)
        self.assertIn('total_ms', timings)


if __name__ == '__main__':
    unittest.main()
