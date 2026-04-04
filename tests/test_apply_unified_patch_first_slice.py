from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.patching import apply_unified_patch_to_file


class ApplyUnifiedPatchFirstSliceTests(unittest.TestCase):
    def test_apply_unified_patch_to_file_updates_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "notes.txt"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

            patch = "\n".join(
                [
                    "--- a/notes.txt",
                    "+++ b/notes.txt",
                    "@@ -1,3 +1,3 @@",
                    " alpha",
                    "-beta",
                    "+BETA",
                    " gamma",
                ]
            )

            result = apply_unified_patch_to_file(
                workspace_root=workspace,
                path="notes.txt",
                patch=patch,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["mutation_kind"], "apply_unified_patch")
            self.assertEqual(result["hunk_count"], 1)
            self.assertEqual(result["applied_hunk_count"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nBETA\ngamma\n")

    def test_apply_unified_patch_fails_on_context_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "notes.txt"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

            patch = "\n".join(
                [
                    "--- a/notes.txt",
                    "+++ b/notes.txt",
                    "@@ -1,3 +1,3 @@",
                    " alpha",
                    "-delta",
                    "+BETA",
                    " gamma",
                ]
            )

            result = apply_unified_patch_to_file(
                workspace_root=workspace,
                path="notes.txt",
                patch=patch,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "hunk_context_mismatch")
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nbeta\ngamma\n")

    def test_apply_unified_patch_fails_on_declared_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "notes.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            patch = "\n".join(
                [
                    "--- a/other.txt",
                    "+++ b/other.txt",
                    "@@ -1,2 +1,2 @@",
                    " alpha",
                    "-beta",
                    "+BETA",
                ]
            )

            result = apply_unified_patch_to_file(
                workspace_root=workspace,
                path="notes.txt",
                patch=patch,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "patch_path_mismatch")


if __name__ == "__main__":
    unittest.main()
