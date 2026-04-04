from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime.core.session_manager import SessionManager
from orbit.runtime.execution.contracts.plans import ToolRequest
from orbit.store.sqlite_store import SQLiteStore


class _UnusedBackend:
    backend_name = "test-backend"

    def plan_from_messages(self, messages, session=None):  # pragma: no cover
        raise AssertionError("plan_from_messages should not be called in this test")


class ApplyUnifiedPatchSessionRuntimeTests(unittest.TestCase):
    def test_apply_unified_patch_is_blocked_without_fresh_full_read_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
            store = SQLiteStore(workspace / ".orbit" / "orbit.db")
            manager = SessionManager(
                store=store,
                backend=_UnusedBackend(),
                workspace_root=str(workspace),
                enable_mcp_filesystem=True,
            )
            session = manager.create_session(backend_name="test", model="test-model")

            tool_request = ToolRequest(
                tool_name="apply_unified_patch",
                input_payload={
                    "path": "notes.txt",
                    "patch": "\n".join(
                        [
                            "--- a/notes.txt",
                            "+++ b/notes.txt",
                            "@@ -1,3 +1,3 @@",
                            " alpha",
                            "-beta",
                            "+BETA",
                            " gamma",
                        ]
                    ),
                },
                requires_approval=True,
                side_effect_class="write",
            )

            result = manager.execute_tool_request(session=session, tool_request=tool_request)
            self.assertFalse(result.ok)
            self.assertEqual(result.data["failure_layer"], "grounding_readiness")
            self.assertEqual(result.data["mutation_kind"], "apply_unified_patch")
            self.assertEqual(result.data["write_readiness"]["reason"], "no_prior_grounding")
            self.assertEqual((workspace / "notes.txt").read_text(encoding="utf-8"), "alpha\nbeta\ngamma\n")

    def test_apply_unified_patch_executes_after_fresh_full_read_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "notes.txt"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
            store = SQLiteStore(workspace / ".orbit" / "orbit.db")
            manager = SessionManager(
                store=store,
                backend=_UnusedBackend(),
                workspace_root=str(workspace),
                enable_mcp_filesystem=True,
            )
            session = manager.create_session(backend_name="test", model="test-model")

            read_request = ToolRequest(
                tool_name="read_file",
                input_payload={"path": "notes.txt"},
                requires_approval=False,
                side_effect_class="safe",
            )
            read_result = manager.execute_tool_request(session=session, tool_request=read_request)
            self.assertTrue(read_result.ok)
            manager.record_filesystem_read_state(session=session, tool_request=read_request, tool_result=read_result)

            patch_request = ToolRequest(
                tool_name="apply_unified_patch",
                input_payload={
                    "path": "notes.txt",
                    "patch": "\n".join(
                        [
                            "--- a/notes.txt",
                            "+++ b/notes.txt",
                            "@@ -1,3 +1,3 @@",
                            " alpha",
                            "-beta",
                            "+BETA",
                            " gamma",
                        ]
                    ),
                },
                requires_approval=True,
                side_effect_class="write",
            )

            result = manager.execute_tool_request(session=session, tool_request=patch_request)
            self.assertTrue(result.ok)
            self.assertEqual(result.data["raw_result"]["structuredContent"]["mutation_kind"], "apply_unified_patch")
            self.assertEqual(result.data["raw_result"]["structuredContent"]["applied_hunk_count"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nBETA\ngamma\n")


if __name__ == "__main__":
    unittest.main()
