from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import build_codex_session_manager
from orbit.runtime.execution.contracts.plans import ToolRequest


class ProcessMcpSessionInjectionTests(unittest.TestCase):
    def test_start_process_executes_with_runtime_injected_session_id(self):
        sm = build_codex_session_manager(
            model="gpt-5.4",
            enable_tools=True,
            enable_mcp_filesystem=True,
            enable_mcp_bash=True,
            enable_mcp_process=True,
        )
        session = sm.create_session(backend_name="openai-codex", model="gpt-5.4")

        result = sm.execute_tool_request(
            session=session,
            tool_request=ToolRequest(
                tool_name="start_process",
                input_payload={"command": "python -m http.server 8765", "cwd": "."},
                requires_approval=False,
                side_effect_class="execute",
            ),
        )

        self.assertTrue(result.ok)
        structured = result.data.get("raw_result", {}).get("structuredContent", {})
        process = structured.get("process", structured)
        self.assertEqual(process.get("session_id"), session.session_id)
        process_id = process.get("process_id")
        self.assertIsInstance(process_id, str)
        self.assertTrue(process_id)

        terminate = sm.execute_tool_request(
            session=session,
            tool_request=ToolRequest(
                tool_name="terminate_process",
                input_payload={"process_id": process_id},
                requires_approval=False,
                side_effect_class="execute",
            ),
        )
        self.assertTrue(terminate.ok)


if __name__ == "__main__":
    unittest.main()
