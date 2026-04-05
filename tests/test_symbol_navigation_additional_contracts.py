from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import (
    _find_references_result,
    _read_symbol_body_result,
)


class SymbolNavigationAdditionalContractTests(unittest.TestCase):
    def test_find_references_returns_cross_language_candidates_in_mixed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.py").write_text("print(Alpha)\n", encoding="utf-8")
            (workspace / "b.ts").write_text("console.log(Alpha)\n", encoding="utf-8")
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
            self.assertEqual(sorted(item["path"] for item in result["references"]), ["a.py", "b.ts"])

    def test_find_references_path_scope_filters_mixed_language_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            py_pkg = workspace / "py_pkg"
            ts_pkg = workspace / "ts_pkg"
            py_pkg.mkdir()
            ts_pkg.mkdir()
            (py_pkg / "one.py").write_text("print(Alpha)\n", encoding="utf-8")
            (ts_pkg / "two.ts").write_text("console.log(Alpha)\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_references_result("Alpha", path="py_pkg")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["reference_count"], 1)
            self.assertEqual(result["references"][0]["path"], "py_pkg/one.py")

    def test_read_symbol_body_currently_fails_cleanly_for_ambiguous_repeated_method_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "class Alpha:\n"
                "    def run(self):\n"
                "        return 'alpha'\n\n"
                "class Beta:\n"
                "    def run(self):\n"
                "        return 'beta'\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.py", "run", kind="method")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "symbol_ambiguous")
            self.assertIn("disambiguation_hint", result)
            self.assertIn("narrower path", result["disambiguation_hint"])


if __name__ == "__main__":
    unittest.main()
