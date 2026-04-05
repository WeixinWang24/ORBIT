from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _read_symbol_body_result


class ReadSymbolBodyFirstSliceTests(unittest.TestCase):
    def test_read_symbol_body_returns_python_function_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "def helper(x):\n"
                "    y = x + 1\n"
                "    return y\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.py", "helper")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "function")
            self.assertEqual(result["header"], "def helper(x):")
            self.assertIn("return y", result["body"])

    def test_read_symbol_body_returns_method_body_with_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "class Alpha:\n"
                "    def run(self):\n"
                "        return 1\n",
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

            self.assertTrue(result["ok"])
            self.assertEqual(result["container"], "Alpha")
            self.assertIn("def run(self):", result["body"])

    def test_read_symbol_body_disambiguates_repeated_methods_by_container(self) -> None:
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
                result = _read_symbol_body_result("sample.py", "run", kind="method", container="Beta")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertTrue(result["ok"])
            self.assertEqual(result["container"], "Beta")
            self.assertEqual(result["requested_container"], "Beta")
            self.assertIn("return 'beta'", result["body"])

    def test_read_symbol_body_fails_cleanly_for_wrong_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "class Alpha:\n"
                "    def run(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.py", "run", kind="method", container="Beta")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "symbol_not_found")
            self.assertEqual(result["container"], "Beta")

    def test_read_symbol_body_fails_cleanly_for_missing_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text("def helper():\n    return 1\n", encoding="utf-8")
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _read_symbol_body_result("sample.py", "missing")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "symbol_not_found")


if __name__ == "__main__":
    unittest.main()
