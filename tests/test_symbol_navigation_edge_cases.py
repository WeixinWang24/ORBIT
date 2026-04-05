from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

from src.mcp_servers.system.core.filesystem.stdio_server import (
    _find_symbol_result,
    _read_symbol_body_result,
    _get_symbols_overview_result,
)


class SymbolNavigationEdgeCaseTests(unittest.TestCase):
    def test_find_symbol_returns_cross_language_matches_in_mixed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (workspace / "b.ts").write_text("export class Alpha {}\n", encoding="utf-8")
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
            self.assertEqual(sorted(item["path"] for item in result["matches"]), ["a.py", "b.ts"])

    def test_find_symbol_path_scope_filters_mixed_language_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            py_pkg = workspace / "py_pkg"
            ts_pkg = workspace / "ts_pkg"
            py_pkg.mkdir()
            ts_pkg.mkdir()
            (py_pkg / "one.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (ts_pkg / "two.ts").write_text("export class Alpha {}\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _find_symbol_result("Alpha", path="ts_pkg", kind="class")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["match_count"], 1)
            self.assertEqual(result["matches"][0]["path"], "ts_pkg/two.ts")

    def test_get_symbols_overview_rejects_unsupported_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.md"
            target.write_text("# hello\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                with self.assertRaises(ValueError):
                    _get_symbols_overview_result("sample.md")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

    def test_read_symbol_body_rejects_unsupported_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.md"
            target.write_text("# hello\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                with self.assertRaises(ValueError):
                    _read_symbol_body_result("sample.md", "hello")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

    def test_get_symbols_overview_normalizes_ts_js_subprocess_failure_to_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.ts"
            target.write_text("export class Alpha {}\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                with patch(
                    "src.mcp_servers.system.core.filesystem.stdio_server.subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, ["node"], stderr="synthetic ts failure"),
                ):
                    with self.assertRaises(ValueError) as ctx:
                        _get_symbols_overview_result("sample.ts")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertIn("synthetic ts failure", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
