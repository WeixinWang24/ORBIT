from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _read_symbol_body_result


class ReadSymbolBodyTsJsFirstSliceTests(unittest.TestCase):
    def test_read_symbol_body_returns_typescript_function_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.ts"
            target.write_text(
                "export function helper(x: number) {\n"
                "  const y = x + 1\n"
                "  return y\n"
                "}\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.ts", "helper", kind="function")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertEqual(result["language"], "typescript")
            self.assertIn("return y", result["body"])

    def test_read_symbol_body_returns_js_method_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.js"
            target.write_text(
                "class Alpha {\n"
                "  run() {\n"
                "    return 1\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.js", "run", kind="method")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertEqual(result["language"], "javascript")
            self.assertEqual(result["container"], "Alpha")
            self.assertIn("run()", result["body"])
            self.assertIn("return 1", result["body"])

    def test_read_symbol_body_disambiguates_repeated_js_methods_by_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.js"
            target.write_text(
                "class Alpha {\n"
                "  run() {\n"
                "    return 'alpha'\n"
                "  }\n"
                "}\n\n"
                "class Beta {\n"
                "  run() {\n"
                "    return 'beta'\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.js", "run", kind="method", container="Beta")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertEqual(result["container"], "Beta")
            self.assertEqual(result["requested_container"], "Beta")
            self.assertIn("return 'beta'", result["body"])

    def test_read_symbol_body_returns_single_line_arrow_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.js"
            target.write_text("const helper = () => 1\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.js", "helper", kind="function")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertIn("const helper = () => 1", result["body"])


if __name__ == "__main__":
    unittest.main()
