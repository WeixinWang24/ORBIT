from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime import DummyExecutionBackend, SessionManager
from orbit.runtime.execution.contracts.plans import ToolRequest
from orbit.store.sqlite_store import SQLiteStore


class EvoGroundedSelfAuthoringIntegrationTests(unittest.TestCase):
    def test_evo_mode_can_execute_grounded_repo_root_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "sample.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            store = SQLiteStore(db_path=repo / "orbit.db")
            manager = SessionManager(
                store=store,
                backend=DummyExecutionBackend(),
                workspace_root=str(repo),
                runtime_mode="evo",
                enable_mcp_filesystem=True,
            )
            session = manager.create_session(backend_name="dummy", model="dummy")

            read_request = ToolRequest(
                tool_name="read_file",
                input_payload={"path": "sample.txt"},
                side_effect_class="safe",
                requires_approval=False,
            )
            read_result = manager.execute_tool_request(session=session, tool_request=read_request)
            self.assertTrue(read_result.ok)
            manager.record_filesystem_read_state(session=session, tool_request=read_request, tool_result=read_result)

            refreshed = manager.get_session(session.session_id)
            assert refreshed is not None
            replace_request = ToolRequest(
                tool_name="replace_in_file",
                input_payload={"path": "sample.txt", "old_text": "beta", "new_text": "BETA"},
                side_effect_class="write",
                requires_approval=False,
            )
            blocked = manager.maybe_block_write_for_grounding(session=refreshed, tool_request=replace_request)
            self.assertIsNone(blocked)

            replace_result = manager.execute_tool_request(session=refreshed, tool_request=replace_request)
            self.assertTrue(replace_result.ok)
            structured = (((replace_result.data or {}).get("raw_result") or {}).get("structuredContent") or {})
            self.assertEqual(structured.get("mutation_kind"), "replace_in_file")
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nBETA\n")


if __name__ == "__main__":
    unittest.main()
