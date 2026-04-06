from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.models import ConversationSession
from orbit.runtime.core.session_manager import SessionManager
from orbit.runtime.execution.contracts.plans import ToolRequest
from orbit.runtime.governance.protocol.mode import mode_policy_summary, workspace_root_for_runtime_mode
from orbit.runtime import DummyExecutionBackend
from orbit.store.sqlite_store import SQLiteStore


class EvoGroundedSelfAuthoringFirstSliceTests(unittest.TestCase):
    def test_evo_mode_policy_declares_grounded_self_authoring(self) -> None:
        policy = mode_policy_summary("evo")
        self.assertEqual(policy["self_runtime_visibility"], "repo_root")
        self.assertEqual(policy["self_modification_posture"], "phase_a_grounded_self_authoring")

    def test_workspace_root_for_evo_mode_is_repo_root(self) -> None:
        root = workspace_root_for_runtime_mode("evo")
        self.assertTrue(str(root).endswith("/ORBIT"))

    def test_evo_mutation_requires_fresh_full_read_grounding(self) -> None:
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
            request = ToolRequest(
                tool_name="replace_in_file",
                input_payload={"path": "sample.txt", "old_text": "beta", "new_text": "BETA"},
                side_effect_class="write",
                requires_approval=False,
            )
            blocked = manager.maybe_block_write_for_grounding(session=session, tool_request=request)
            self.assertIsNotNone(blocked)
            assert blocked is not None
            self.assertFalse(blocked.ok)
            self.assertEqual(blocked.data["failure_layer"], "grounding_readiness")
            self.assertEqual(blocked.data["write_readiness"]["reason"], "no_prior_grounding")

    def test_evo_mutation_allows_after_fresh_full_read_grounding(self) -> None:
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
                    "source_tool": "read_file",
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
            request = ToolRequest(
                tool_name="replace_in_file",
                input_payload={"path": "sample.txt", "old_text": "beta", "new_text": "BETA"},
                side_effect_class="write",
                requires_approval=False,
            )
            blocked = manager.maybe_block_write_for_grounding(session=refreshed, tool_request=request)
            self.assertIsNone(blocked)


if __name__ == "__main__":
    unittest.main()
