from __future__ import annotations

import unittest
from pathlib import Path

from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig, SessionManagerRuntimeAdapter
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server


class ProcessMcpSessionInjectionTests(unittest.TestCase):
    def test_process_bootstrap_declares_persistent_preferred(self):
        workspace_root = str(Path(__file__).resolve().parents[1])
        bootstrap = bootstrap_local_process_mcp_server(workspace_root=workspace_root)
        self.assertEqual(bootstrap.continuity_mode, "persistent_preferred")

    def test_process_profile_mount_exposes_process_tools_on_current_adapter_surface(self):
        adapter = SessionManagerRuntimeAdapter.build(
            config=RuntimeAdapterConfig(
                runtime_profile="mcp_default",
                filesystem=True,
                bash=True,
                process=True,
            )
        )

        tool_names = {tool.tool_name for tool in adapter.list_available_tools()}
        self.assertIn("start_process", tool_names)
        self.assertIn("read_process_output", tool_names)
        self.assertIn("wait_process", tool_names)
        self.assertIn("terminate_process", tool_names)

        backend_registry = getattr(adapter.session_manager.backend, "tool_registry", None)
        self.assertIsNotNone(backend_registry)
        backend_tool_names = {tool.name for tool in backend_registry.list_tools()}
        self.assertIn("start_process", backend_tool_names)
        self.assertIn("read_process_output", backend_tool_names)
        self.assertIn("wait_process", backend_tool_names)
        self.assertIn("terminate_process", backend_tool_names)


if __name__ == "__main__":
    unittest.main()
