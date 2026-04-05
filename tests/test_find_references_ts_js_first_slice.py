from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _find_references_result


class FindReferencesTsJsFirstSliceTests(unittest.TestCase):
    def test_find_references_returns_ts_js_candidate_usages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.ts").write_text(
                "export class Alpha {}\n"
                "const value = new Alpha()\n"
                "console.log(Alpha)\n",
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
            self.assertIn("const value = new Alpha()", previews)
            self.assertIn("console.log(Alpha)", previews)

    def test_find_references_respects_ts_js_path_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            pkg = workspace / "pkg"
            pkg.mkdir()
            (pkg / "one.js").write_text("console.log(Alpha)\n", encoding="utf-8")
            (workspace / "two.ts").write_text("console.log(Alpha)\n", encoding="utf-8")
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
            self.assertEqual(result["references"][0]["path"], "pkg/one.js")


if __name__ == "__main__":
    unittest.main()
