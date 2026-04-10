from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import build_codex_session_manager_for_profile
from orbit.interfaces.runtime_profile import RuntimeProfileSpec, resolve_runtime_profile
from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile


class SessionManagerProfileTests(unittest.TestCase):
    def test_session_manager_records_current_build_and_activation_metrics(self) -> None:
        profile = RuntimeProfileSpec(
            name="mcp_default",
            runtime_mode="evo",
            capability_profile=RuntimeCapabilityProfile(filesystem=True, browser=True),
        )
        manager, _composer, _bundle = build_codex_session_manager_for_profile(profile=profile)

        build_timings = getattr(manager, "metadata", {}).get("build_profile_timings", {})
        activation_metrics = getattr(manager, "metadata", {}).get("capability_activation_metrics", {})
        session_manager_timings = getattr(manager, "metadata", {}).get("session_manager_profile_timings", {})

        self.assertIn("workspace_select_ms", build_timings)
        self.assertIn("backend_init_ms", build_timings)
        self.assertIn("capability_activate_ms", build_timings)
        self.assertIn("session_manager_init_ms", build_timings)
        self.assertIn("total_ms", build_timings)

        self.assertIn("tool_registry_init_ms", activation_metrics)
        self.assertIn("filesystem_activation_ms", activation_metrics)
        self.assertIn("browser_activation_ms", activation_metrics)
        self.assertIn("total_ms", activation_metrics)

        self.assertIn("total_ms", session_manager_timings)


if __name__ == '__main__':
    unittest.main()
