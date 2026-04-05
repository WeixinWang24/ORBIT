from __future__ import annotations

import unittest
from datetime import datetime, timezone

from orbit.interfaces.contracts import InterfaceSession
from orbit.interfaces.runtime_cli_render import status_body_lines
from orbit.interfaces.runtime_cli_state import RuntimeCliState, STATUS_MODE


class MockOrbitChatAdapter:
    def __init__(self) -> None:
        self._session = InterfaceSession(
            session_id='mock-session',
            conversation_id='mock-conv',
            backend_name='mock',
            model='mock-model',
            runtime_mode='evo',
            workspace_root='/tmp/orbit-root',
            mode_policy_profile='evo-phase-a',
            self_runtime_visibility='repo_root',
            self_modification_posture='phase_a_read_heavy',
            updated_at=datetime.now(timezone.utc),
            status='active',
        )

    def get_session(self, session_id: str):
        return self._session

    def create_session(self, **kwargs):
        return self._session

    def list_sessions(self):
        return [self._session]

    def get_workbench_status(self):
        return {
            'adapter_kind': 'mock',
            'runtime_mode': 'evo',
            'workspace_root': '/tmp/orbit-root',
            'mode_policy_profile': 'evo-phase-a',
            'self_runtime_visibility': 'repo_root',
            'self_modification_posture': 'phase_a_read_heavy',
            'active_build_id': 'stable-build-001',
            'candidate_build_id': 'candidate-build-002',
            'last_known_good_build_id': 'stable-build-000',
            'session_count': 1,
            'approval_count': 0,
            'registered_tool_count': 3,
            'registered_tool_names': ['native__list_available_tools', 'run_bash', 'web_fetch'],
            'build_profile_timings': {'total_ms': 123.4, 'backend_init_ms': 50.0},
            'session_manager_profile_timings': {'mcp_filesystem_ms': 6000.0, 'memory_service_init_ms': 3000.0, 'total_ms': 12000.0},
            'startup_metrics': {'first_frame_ms': 320.0, 'adapter_build_ms': 1400.0, 'pty_import_profile_timings': {'runtime_cli_render_ms': 71.0}, 'runtime_adapter_import_profile_timings': {'orbit_runtime_ms': 4200.0}},
        }


class StatusRenderScrollTests(unittest.TestCase):
    def test_status_body_lines_include_scrollable_details_section(self) -> None:
        adapter = MockOrbitChatAdapter()
        state = RuntimeCliState(mode=STATUS_MODE, active_session_id='mock-session')
        lines = status_body_lines(state, adapter, 100)

        joined = '\n'.join(lines)
        self.assertIn('Scrollable details', joined)
        self.assertIn('build_profile_timings', joined)
        self.assertIn('session_manager_profile_timings', joined)
        self.assertIn('memory_service_init_ms=3000.0', joined)
        self.assertIn('startup_metrics', joined)
        self.assertIn('first_frame_ms=320.0', joined)
        self.assertIn('pty_import_profile_timings', joined)
        self.assertIn('runtime_cli_render_ms=71.0', joined)
        self.assertIn('runtime_adapter_import_profile_timings', joined)
        self.assertIn('orbit_runtime_ms=4200.0', joined)
        self.assertIn('registered_tools:', joined)


if __name__ == '__main__':
    unittest.main()
