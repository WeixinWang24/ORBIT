from __future__ import annotations

import unittest
from pathlib import Path

from orbit.interfaces.runtime_adapter import build_codex_session_manager


class BrowserMcpInteractionFirstPassTests(unittest.TestCase):
    def test_explicit_browser_mcp_codex_session_manager_mounts_browser_tools_via_mcp(self) -> None:
        sm = build_codex_session_manager(model="gpt-5.4", enable_mcp_browser=True)
        for name in [
            "browser_open",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_console",
            "browser_screenshot",
        ]:
            tool = sm.tool_registry.get(name)
            self.assertEqual(type(tool).__name__, "McpToolWrapper")
            self.assertEqual(getattr(tool, "tool_source", None), "mcp")
            self.assertEqual(getattr(tool, "server_name", None), "browser")

    def test_browser_mcp_tools_run_fixture_interaction_loop(self) -> None:
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()
        sm = build_codex_session_manager(model="gpt-5.4", enable_mcp_browser=True)

        opened = sm.tool_registry.get("browser_open").invoke(url=url)
        self.assertTrue(opened.ok, opened.content)

        snap1 = sm.tool_registry.get("browser_snapshot").invoke()
        self.assertTrue(snap1.ok, snap1.content)
        elements1 = snap1.data["raw_result"]["structuredContent"]["elements"]
        button = next(item for item in elements1 if item["tag"] == "button")
        input_el = next(item for item in elements1 if item["tag"] == "input")

        clicked = sm.tool_registry.get("browser_click").invoke(element_id=button["id"])
        self.assertTrue(clicked.ok, clicked.content)
        snap2 = sm.tool_registry.get("browser_snapshot").invoke()
        elements2 = snap2.data["raw_result"]["structuredContent"]["elements"]
        self.assertTrue(any(item.get("text") == "Clicked!" for item in elements2))

        typed = sm.tool_registry.get("browser_type").invoke(element_id=input_el["id"], text="hello mcp")
        self.assertTrue(typed.ok, typed.content)
        snap3 = sm.tool_registry.get("browser_snapshot").invoke()
        elements3 = snap3.data["raw_result"]["structuredContent"]["elements"]
        self.assertTrue(any(item.get("text") == "hello mcp" for item in elements3))
        refreshed_input = next(item for item in elements3 if item["tag"] == "input")
        self.assertEqual(refreshed_input.get("value"), "hello mcp")

        console = sm.tool_registry.get("browser_console").invoke()
        self.assertTrue(console.ok, console.content)
        messages = console.data["raw_result"]["structuredContent"]["messages"]
        texts = [item.get("text", "") for item in messages]
        self.assertTrue(any("primary-action-clicked" in text for text in texts))
        self.assertTrue(any("input-updated:hello mcp" in text for text in texts))

        shot = sm.tool_registry.get("browser_screenshot").invoke()
        self.assertTrue(shot.ok, shot.content)
        path = Path(shot.data["raw_result"]["structuredContent"]["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".png")


if __name__ == "__main__":
    unittest.main()
