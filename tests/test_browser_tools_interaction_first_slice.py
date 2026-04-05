from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.tools.registry import ToolRegistry


class BrowserToolsInteractionFirstSliceTests(unittest.TestCase):
    def test_browser_interaction_tools_are_not_registered_natively_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            names = registry.list_names()
            self.assertNotIn("browser_click", names)
            self.assertNotIn("browser_type", names)
            self.assertNotIn("browser_console", names)

    def test_browser_click_type_and_console_against_fixture(self) -> None:
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir), enable_native_browser_tools=True)
            opened = registry.get("browser_open").invoke(url=url)
            self.assertTrue(opened.ok, opened.content)

            snap1 = registry.get("browser_snapshot").invoke()
            self.assertTrue(snap1.ok, snap1.content)
            button = next(item for item in snap1.data["elements"] if item["tag"] == "button")
            input_el = next(item for item in snap1.data["elements"] if item["tag"] == "input")
            self.assertTrue(button["clickable"])
            self.assertTrue(input_el["typeable"])

            clicked = registry.get("browser_click").invoke(element_id=button["id"])
            self.assertTrue(clicked.ok, clicked.content)
            snap2 = registry.get("browser_snapshot").invoke()
            self.assertTrue(any(item.get("text") == "Clicked!" for item in snap2.data["elements"]))

            typed = registry.get("browser_type").invoke(element_id=input_el["id"], text="hello orbit")
            self.assertTrue(typed.ok, typed.content)
            snap3 = registry.get("browser_snapshot").invoke()
            mirrored = [item for item in snap3.data["elements"] if item.get("text") == "hello orbit"]
            self.assertTrue(mirrored)
            refreshed_input = next(item for item in snap3.data["elements"] if item["tag"] == "input")
            self.assertEqual(refreshed_input.get("value"), "hello orbit")

            console = registry.get("browser_console").invoke()
            self.assertTrue(console.ok, console.content)
            texts = [item.get("text", "") for item in console.data["messages"]]
            self.assertTrue(any("primary-action-clicked" in text for text in texts))
            self.assertTrue(any("input-updated:hello orbit" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
