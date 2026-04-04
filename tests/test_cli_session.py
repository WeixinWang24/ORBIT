from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import build_codex_session_manager


class CliSessionWiringTests(unittest.TestCase):
    def testbuild_codex_session_manager_registers_full_stack_mcp_tools_when_enabled(self):
        sm = build_codex_session_manager(
            model="gpt-5.4",
            enable_tools=True,
            enable_mcp_filesystem=True,
            enable_mcp_bash=True,
            enable_mcp_process=True,
        )

        tool_names = {tool.name for tool in sm.tool_registry.list_tools()}

        self.assertIn("read_file", tool_names)
        self.assertIn("glob", tool_names)
        self.assertIn("grep", tool_names)
        self.assertIn("todo_write", tool_names)
        self.assertIn("web_fetch", tool_names)
        self.assertIn("run_bash", tool_names)
        self.assertIn("start_process", tool_names)
        self.assertIn("read_process_output", tool_names)
        self.assertIn("wait_process", tool_names)
        self.assertIn("terminate_process", tool_names)

        backend_registry = getattr(sm.backend, "tool_registry", None)
        self.assertIsNotNone(backend_registry)
        backend_tool_names = {tool.name for tool in backend_registry.list_tools()}
        self.assertEqual(tool_names, backend_tool_names)


if __name__ == "__main__":
    unittest.main()
