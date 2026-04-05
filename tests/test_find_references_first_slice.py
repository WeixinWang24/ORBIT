from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _find_references_result


class FindReferencesFirstSliceTests(unittest.TestCase):
    def test_find_references_returns_candidate_usages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.py").write_text(
                "class Alpha:\n"
                "    pass\n\n"
                "value = Alpha()\n"
                "print(Alpha)\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_references_result("Alpha")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["reference_count"], 2)
            previews = [item["preview"] for item in result["references"]]
            self.assertIn("value = Alpha()", previews)
            self.assertIn("print(Alpha)", previews)

    def test_find_references_respects_path_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            pkg = workspace / "pkg"
            pkg.mkdir()
            (pkg / "one.py").write_text("print(Alpha)\n", encoding="utf-8")
            (workspace / "two.py").write_text("print(Alpha)\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_references_result("Alpha", path="pkg")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["reference_count"], 1)
            self.assertEqual(result["references"][0]["path"], "pkg/one.py")


if __name__ == "__main__":
    unittest.main()
