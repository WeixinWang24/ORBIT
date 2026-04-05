from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _find_symbol_result


class FindSymbolFirstSliceTests(unittest.TestCase):
    def test_find_symbol_searches_workspace_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (workspace / "b.py").write_text("def Alpha():\n    return 1\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_symbol_result("Alpha")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["match_count"], 2)
            kinds = sorted(item["kind"] for item in result["matches"])
            self.assertEqual(kinds, ["class", "function"])

    def test_find_symbol_disambiguates_repeated_methods_by_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "class Alpha:\n"
                "    def run(self):\n"
                "        return 1\n\n"
                "class Beta:\n"
                "    def run(self):\n"
                "        return 2\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_symbol_result("run", kind="method", container="Beta")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["match_count"], 1)
            self.assertEqual(result["container"], "Beta")
            self.assertEqual(result["matches"][0]["container"], "Beta")

    def test_find_symbol_respects_kind_and_path_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            pkg = workspace / "pkg"
            pkg.mkdir()
            (pkg / "one.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (workspace / "two.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_symbol_result("Alpha", path="pkg", kind="class")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["match_count"], 1)
            self.assertEqual(result["matches"][0]["path"], "pkg/one.py")
            self.assertEqual(result["matches"][0]["kind"], "class")


if __name__ == "__main__":
    unittest.main()
