from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _find_symbol_result


class FindSymbolTsJsFirstSliceTests(unittest.TestCase):
    def test_find_symbol_searches_typescript_and_javascript_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "a.ts").write_text("export class Alpha {}\n", encoding="utf-8")
            (workspace / "b.js").write_text("function Alpha() { return 1 }\n", encoding="utf-8")
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
            paths = sorted(item["path"] for item in result["matches"])
            self.assertEqual(paths, ["a.ts", "b.js"])

    def test_find_symbol_disambiguates_repeated_ts_js_methods_by_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.js"
            target.write_text(
                "class Alpha {\n"
                "  run() { return 1 }\n"
                "}\n\n"
                "class Beta {\n"
                "  run() { return 2 }\n"
                "}\n",
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

    def test_find_symbol_respects_ts_js_path_scope_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            pkg = workspace / "pkg"
            pkg.mkdir()
            (pkg / "one.ts").write_text("export class Alpha {}\n", encoding="utf-8")
            (workspace / "two.js").write_text("function Alpha() { return 1 }\n", encoding="utf-8")
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
            self.assertEqual(result["matches"][0]["path"], "pkg/one.ts")
            self.assertEqual(result["matches"][0]["kind"], "class")


if __name__ == "__main__":
    unittest.main()
