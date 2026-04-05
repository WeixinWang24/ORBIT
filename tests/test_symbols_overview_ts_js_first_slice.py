from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.filesystem.stdio_server import _get_symbols_overview_result


class SymbolsOverviewTsJsFirstSliceTests(unittest.TestCase):
    def test_get_symbols_overview_returns_typescript_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.ts"
            target.write_text(
                "export class Alpha {\n"
                "  methodOne() { return 1 }\n"
                "}\n\n"
                "export function topLevel() { return 2 }\n"
                "export const arrowThing = () => 3\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _get_symbols_overview_result("sample.ts")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["language"], "typescript")
            names = {(item["name"], item["kind"], item["container"]) for item in result["symbols"]}
            self.assertIn(("Alpha", "class", None), names)
            self.assertIn(("methodOne", "method", "Alpha"), names)
            self.assertIn(("topLevel", "function", None), names)
            self.assertIn(("arrowThing", "function", None), names)

    def test_get_symbols_overview_returns_javascript_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "sample.js"
            target.write_text(
                "class Beta {\n"
                "  async load() { return 1 }\n"
                "}\n\n"
                "const helper = async () => 2\n",
                encoding="utf-8",
            )
            old = os.environ.get("ORBIT_WORKSPACE_ROOT")
            os.environ["ORBIT_WORKSPACE_ROOT"] = str(workspace)
            try:
                result = _get_symbols_overview_result("sample.js")
            finally:
                if old is None:
                    os.environ.pop("ORBIT_WORKSPACE_ROOT", None)
                else:
                    os.environ["ORBIT_WORKSPACE_ROOT"] = old

            self.assertEqual(result["language"], "javascript")
            names = {(item["name"], item["kind"], item["container"]) for item in result["symbols"]}
            self.assertIn(("Beta", "class", None), names)
            self.assertIn(("load", "async_method", "Beta"), names)
            self.assertIn(("helper", "async_function", None), names)


if __name__ == "__main__":
    unittest.main()
