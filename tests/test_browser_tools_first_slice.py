from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.tools.registry import ToolRegistry


class BrowserToolsFirstSliceTests(unittest.TestCase):
    def test_browser_tools_are_not_registered_natively_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            names = registry.list_names()
            self.assertNotIn("browser_open", names)
            self.assertNotIn("browser_snapshot", names)
            self.assertNotIn("browser_screenshot", names)

    def test_browser_tools_can_still_be_registered_natively_for_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir), enable_native_browser_tools=True)
            names = registry.list_names()
            self.assertIn("browser_open", names)
            self.assertIn("browser_snapshot", names)
            self.assertIn("browser_screenshot", names)

    def test_browser_open_snapshot_and_screenshot_against_fixture(self) -> None:
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir), enable_native_browser_tools=True)

            opened = registry.get("browser_open").invoke(url=url)
            if not opened.ok and "Playwright is not available" in opened.content:
                self.skipTest(opened.content)
            self.assertTrue(opened.ok, opened.content)
            self.assertIn("ORBIT Browser Fixture", opened.data.get("title", ""))

            snap = registry.get("browser_snapshot").invoke()
            self.assertTrue(snap.ok, snap.content)
            self.assertEqual(snap.data.get("title"), "ORBIT Browser Fixture")
            self.assertGreaterEqual(snap.data.get("element_count", 0), 4)
            tags = {item.get("tag") for item in snap.data.get("elements", [])}
            self.assertIn("h1", tags)
            self.assertIn("a", tags)
            self.assertIn("button", tags)
            self.assertIn("input", tags)

            shot = registry.get("browser_screenshot").invoke()
            self.assertTrue(shot.ok, shot.content)
            path = Path(shot.data.get("path", ""))
            self.assertTrue(path.exists())
            self.assertEqual(path.suffix, ".png")


if __name__ == "__main__":
    unittest.main()
