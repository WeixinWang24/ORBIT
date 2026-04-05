from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import build_codex_session_manager


class SessionManagerProfileTests(unittest.TestCase):
    def test_session_manager_records_detailed_profile_timings(self) -> None:
        manager = build_codex_session_manager(model='gpt-5.4', runtime_mode='evo')
        timings = getattr(manager, 'metadata', {}).get('session_manager_profile_timings', {})
        self.assertIn('tool_registry_init_ms', timings)
        self.assertIn('mcp_filesystem_ms', timings)
        self.assertIn('mcp_git_ms', timings)
        self.assertIn('mcp_bash_ms', timings)
        self.assertIn('mcp_process_ms', timings)
        self.assertIn('mcp_pytest_ms', timings)
        self.assertIn('embedding_service_init_ms', timings)
        self.assertIn('memory_service_init_ms', timings)
        self.assertIn('total_ms', timings)


if __name__ == '__main__':
    unittest.main()
