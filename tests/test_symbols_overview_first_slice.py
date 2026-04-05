from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _get_symbols_overview_result


class SymbolsOverviewFirstSliceTests(unittest.TestCase):
    def test_get_symbols_overview_returns_python_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.py"
            target.write_text(
                "class Alpha:\n"
                "    def method_one(self):\n"
                "        return 1\n\n"
                "def top_level():\n"
                "    return 2\n\n"
                "async def async_top():\n"
                "    return 3\n",
                encoding="utf-8",
            )

            import os
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _get_symbols_overview_result("sample.py")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["language"], "python")
            names = {(item["name"], item["kind"], item["container"]) for item in result["symbols"]}
            self.assertIn(("Alpha", "class", None), names)
            self.assertIn(("method_one", "method", "Alpha"), names)
            self.assertIn(("top_level", "function", None), names)
            self.assertIn(("async_top", "async_function", None), names)

    def test_get_symbols_overview_rejects_non_python_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.txt"
            target.write_text("hello\n", encoding="utf-8")

            import os
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                with self.assertRaises(ValueError):
                    _get_symbols_overview_result("sample.txt")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old


if __name__ == "__main__":
    unittest.main()
