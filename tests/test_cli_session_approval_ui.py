from __future__ import annotations

import unittest
from unittest.mock import patch

from orbit.interfaces.runtime_adapter import build_codex_session_manager, get_pending_session_approval, resolve_pending_session_approval
from orbit.runtime.execution.contracts.plans import ToolRequest


class CliSessionApprovalUiTests(unittest.TestCase):
    def testresolve_pending_session_approval_approve_clears_pending_state(self):
        sm = build_codex_session_manager(
            model="gpt-5.4",
            enable_tools=True,
            enable_mcp_filesystem=True,
            enable_mcp_bash=True,
            enable_mcp_process=True,
        )
        session = sm.create_session(backend_name="openai-codex", model="gpt-5.4")
        tool_request = ToolRequest(tool_name="start_process", input_payload={"command": "python -m http.server 8765"}, requires_approval=True, side_effect_class="execute")
        plan = sm._open_session_approval(session=session, tool_request=tool_request, plan=type("P", (), {"source_backend": "openai-codex", "plan_label": "test-plan"})())
        self.assertIsNotNone(get_pending_session_approval(sm, session.session_id))

        with patch.object(sm, "_execute_non_approval_tool_closure", return_value=plan):
            resolved = resolve_pending_session_approval(sm, session.session_id, "approve")

        self.assertIsNotNone(resolved)
        self.assertIsNone(get_pending_session_approval(sm, session.session_id))

    def testresolve_pending_session_approval_reject_clears_pending_state(self):
        sm = build_codex_session_manager(
            model="gpt-5.4",
            enable_tools=True,
            enable_mcp_filesystem=True,
            enable_mcp_bash=True,
            enable_mcp_process=True,
        )
        session = sm.create_session(backend_name="openai-codex", model="gpt-5.4")
        tool_request = ToolRequest(tool_name="start_process", input_payload={"command": "python -m http.server 8765"}, requires_approval=True, side_effect_class="execute")
        sm._open_session_approval(session=session, tool_request=tool_request, plan=type("P", (), {"source_backend": "openai-codex", "plan_label": "test-plan"})())
        self.assertIsNotNone(get_pending_session_approval(sm, session.session_id))

        resolved = resolve_pending_session_approval(sm, session.session_id, "reject")

        self.assertIsNotNone(resolved)
        self.assertIsNone(get_pending_session_approval(sm, session.session_id))


if __name__ == "__main__":
    unittest.main()
