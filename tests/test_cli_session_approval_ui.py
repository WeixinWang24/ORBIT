from __future__ import annotations

import unittest
from unittest.mock import Mock

from orbit.interfaces.runtime_adapter import get_pending_session_approval, resolve_pending_session_approval


class CliSessionApprovalUiTests(unittest.TestCase):
    def testresolve_pending_session_approval_approve_clears_pending_state(self):
        session_id = "session-123"
        sm = Mock()
        sm.get_session.return_value = type(
            "Session",
            (),
            {
                "metadata": {
                    "capability_metadata": {
                        "pending_approval": {
                            "approval_request_id": "approval-1",
                            "tool_name": "start_process",
                        }
                    }
                }
            },
        )()
        sm.resolve_session_approval.return_value = {"status": "approved"}

        self.assertIsNotNone(get_pending_session_approval(sm, session_id))
        resolved = resolve_pending_session_approval(sm, session_id, "approve")

        self.assertEqual(resolved, {"status": "approved"})
        sm.resolve_session_approval.assert_called_once_with(
            session_id=session_id,
            approval_request_id="approval-1",
            decision="approve",
            note=None,
        )

    def testresolve_pending_session_approval_reject_clears_pending_state(self):
        session_id = "session-456"
        sm = Mock()
        sm.get_session.return_value = type(
            "Session",
            (),
            {
                "metadata": {
                    "capability_metadata": {
                        "pending_approval": {
                            "approval_request_id": "approval-2",
                            "tool_name": "start_process",
                        }
                    }
                }
            },
        )()
        sm.resolve_session_approval.return_value = {"status": "rejected"}

        self.assertIsNotNone(get_pending_session_approval(sm, session_id))
        resolved = resolve_pending_session_approval(sm, session_id, "reject")

        self.assertEqual(resolved, {"status": "rejected"})
        sm.resolve_session_approval.assert_called_once_with(
            session_id=session_id,
            approval_request_id="approval-2",
            decision="reject",
            note=None,
        )


if __name__ == "__main__":
    unittest.main()
