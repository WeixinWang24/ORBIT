from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime import DummyExecutionBackend, SessionManager
from orbit.runtime.execution.contracts.plans import ToolRequest
from orbit.runtime.governance.grounding_service import GroundingGovernanceService
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
            )
            session = manager.create_session(backend_name="dummy", model="dummy")

            stat = target.stat()
            session.metadata["filesystem_read_state"] = {
                "sample.txt": {
                    "source_tool": "native__read_file",
                    "timestamp_epoch": 0,
                    "is_partial_view": False,
                    "grounding_kind": "full_read",
                    "path_kind": "file",
                    "observed_modified_at_epoch": stat.st_mtime,
                    "observed_size_bytes": stat.st_size,
                    "range": None,
                }
            }
            store.save_session(session)

            refreshed = manager.get_session(session.session_id)
            assert refreshed is not None
            replace_request = ToolRequest(
                tool_name="native__replace_in_file",
                input_payload={"path": "sample.txt", "old_text": "beta", "new_text": "BETA"},
                side_effect_class="write",
                requires_approval=False,
            )
            blocked = GroundingGovernanceService(manager).maybe_block_mutation(session=refreshed, tool_request=replace_request)
            self.assertIsNone(blocked)

            replace_result = manager.execute_tool_request(session=refreshed, tool_request=replace_request)
            self.assertTrue(replace_result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nBETA\n")


if __name__ == "__main__":
    unittest.main()
