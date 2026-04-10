from __future__ import annotations

import unittest
from pathlib import Path

from orbit.interfaces.runtime_adapter import build_codex_session_manager_for_profile
from orbit.interfaces.runtime_profile import RuntimeProfileSpec, resolve_runtime_profile
from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile
from orbit.runtime.mcp.browser_bootstrap import bootstrap_local_browser_mcp_server


class BrowserMcpInteractionFirstPassTests(unittest.TestCase):
    """
    Browser MCP continuity contract tests.

    Contract under test: all browser tools operate against the same single persistent
    browser session managed by a long-lived BrowserManager in the MCP server process.
    Snapshot-local element IDs returned by browser_snapshot are valid targets for
    browser_click and browser_type only because that live session is preserved across
    tool calls. Host process continuity (persistent_required) is what makes this hold.

    If the session were ephemeral (new BrowserManager per call), element IDs from a
    prior snapshot would be invalid, and interaction-after-snapshot would fail.
    """

    def _browser_profile(self) -> RuntimeProfileSpec:
        base = resolve_runtime_profile("mcp_default")
        return RuntimeProfileSpec(
            name=base.name,
            runtime_mode=base.runtime_mode,
            model=base.model,
            enable_tools=base.enable_tools,
            capability_profile=RuntimeCapabilityProfile(filesystem=True, browser=True),
            knowledge_augmentation=base.knowledge_augmentation,
            memory=base.memory,
        )

    def test_browser_bootstrap_declares_persistent_required(self) -> None:
        workspace_root = str(Path(__file__).resolve().parents[1])
        bootstrap = bootstrap_local_browser_mcp_server(workspace_root=workspace_root)
        self.assertEqual(bootstrap.continuity_mode, "persistent_required")

    def test_browser_bootstrap_declares_live_host_capability_metadata(self) -> None:
        workspace_root = str(Path(__file__).resolve().parents[1])
        bootstrap = bootstrap_local_browser_mcp_server(workspace_root=workspace_root)
        meta = bootstrap.capability_metadata
        self.assertIsNotNone(meta, "browser bootstrap must declare capability_metadata")
        self.assertEqual(meta.capability_family, "browser")
        self.assertEqual(meta.continuity_type, "live_host")
        self.assertEqual(meta.truth_source, "live_host_state")
        self.assertEqual(meta.layer_role, "substrate")
        self.assertEqual(meta.transport_importance, "required")

    def test_explicit_browser_mcp_codex_session_manager_mounts_browser_tools_via_mcp(self) -> None:
        _sm, _composer, bundle = build_codex_session_manager_for_profile(profile=self._browser_profile())
        for name in [
            "browser_open",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_console",
            "browser_screenshot",
        ]:
            tool = bundle.tool_registry.get(name)
            self.assertEqual(type(tool).__name__, "McpToolWrapper")
            self.assertEqual(getattr(tool, "tool_source", None), "mcp")
            self.assertEqual(getattr(tool, "server_name", None), "browser")

    def test_snapshot_element_ids_stable_within_live_session(self) -> None:
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()
        _sm, _composer, bundle = build_codex_session_manager_for_profile(profile=self._browser_profile())

        bundle.tool_registry.get("browser_open").invoke(url=url)

        snap1 = bundle.tool_registry.get("browser_snapshot").invoke()
        snap2 = bundle.tool_registry.get("browser_snapshot").invoke()
        self.assertTrue(snap1.ok)
        self.assertTrue(snap2.ok)

        ids1 = {item["id"] for item in snap1.data["raw_result"]["structuredContent"]["elements"] if "id" in item}
        ids2 = {item["id"] for item in snap2.data["raw_result"]["structuredContent"]["elements"] if "id" in item}

        self.assertTrue(ids1, "snap1 must contain at least one element with an id")
        self.assertEqual(ids1, ids2, "element IDs must be stable across snapshots of the same live session")

    def test_browser_mcp_tools_run_fixture_interaction_loop(self) -> None:
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()
        _sm, _composer, bundle = build_codex_session_manager_for_profile(profile=self._browser_profile())

        opened = bundle.tool_registry.get("browser_open").invoke(url=url)
        self.assertTrue(opened.ok, opened.content)

        snap1 = bundle.tool_registry.get("browser_snapshot").invoke()
        self.assertTrue(snap1.ok, snap1.content)
        elements1 = snap1.data["raw_result"]["structuredContent"]["elements"]
        button = next(item for item in elements1 if item["tag"] == "button")
        input_el = next(item for item in elements1 if item["tag"] == "input")

        clicked = bundle.tool_registry.get("browser_click").invoke(element_id=button["id"])
        self.assertTrue(clicked.ok, clicked.content)
        snap2 = bundle.tool_registry.get("browser_snapshot").invoke()
        elements2 = snap2.data["raw_result"]["structuredContent"]["elements"]
        self.assertTrue(any(item.get("text") == "Clicked!" for item in elements2))

        typed = bundle.tool_registry.get("browser_type").invoke(element_id=input_el["id"], text="hello mcp")
        self.assertTrue(typed.ok, typed.content)
        snap3 = bundle.tool_registry.get("browser_snapshot").invoke()
        elements3 = snap3.data["raw_result"]["structuredContent"]["elements"]
        self.assertTrue(any(item.get("text") == "hello mcp" for item in elements3))
        refreshed_input = next(item for item in elements3 if item["tag"] == "input")
        self.assertEqual(refreshed_input.get("value"), "hello mcp")

        console = bundle.tool_registry.get("browser_console").invoke()
        self.assertTrue(console.ok, console.content)
        messages = console.data["raw_result"]["structuredContent"]["messages"]
        texts = [item.get("text", "") for item in messages]
        self.assertTrue(any("primary-action-clicked" in text for text in texts))
        self.assertTrue(any("input-updated:hello mcp" in text for text in texts))

        shot = bundle.tool_registry.get("browser_screenshot").invoke()
        self.assertTrue(shot.ok, shot.content)
        path = Path(shot.data["raw_result"]["structuredContent"]["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".png")


if __name__ == "__main__":
    unittest.main()
