from __future__ import annotations

import unittest
from pathlib import Path

from orbit.interfaces.runtime_adapter import build_codex_session_manager
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

    def test_browser_bootstrap_declares_persistent_required(self) -> None:
        """
        continuity_mode must be persistent_required for the browser family.

        This is the bootstrap-level declaration of the live-host continuity contract:
        the runtime must reuse the same MCP server process (and therefore the same
        BrowserManager and browser context) across all tool calls. A stateless or
        persistent_preferred mode would permit session-breaking restarts.
        """
        workspace_root = str(Path(__file__).resolve().parents[1])
        bootstrap = bootstrap_local_browser_mcp_server(workspace_root=workspace_root)
        self.assertEqual(bootstrap.continuity_mode, "persistent_required")

    def test_browser_bootstrap_declares_live_host_capability_metadata(self) -> None:
        """
        Capability metadata must declare the live-host posture for the browser family.

        transport_importance=required confirms that metadata-aware runtime components
        know not to restart the browser server process between calls.
        """
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

    def test_snapshot_element_ids_stable_within_live_session(self) -> None:
        """
        Continuity contract: snapshot-local element IDs must be stable across
        consecutive snapshots of the same unchanged live page.

        If each snapshot were taken against an independent (non-persistent) browser
        context, element IDs could differ between calls. Stability proves that both
        snapshots observe the same live DOM via the same persistent BrowserManager
        — which is the precondition for browser_click/browser_type to work using
        an element_id from a prior snapshot.
        """
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()
        sm = build_codex_session_manager(model="gpt-5.4", enable_mcp_browser=True)

        sm.tool_registry.get("browser_open").invoke(url=url)

        snap1 = sm.tool_registry.get("browser_snapshot").invoke()
        snap2 = sm.tool_registry.get("browser_snapshot").invoke()
        self.assertTrue(snap1.ok)
        self.assertTrue(snap2.ok)

        ids1 = {item["id"] for item in snap1.data["raw_result"]["structuredContent"]["elements"] if "id" in item}
        ids2 = {item["id"] for item in snap2.data["raw_result"]["structuredContent"]["elements"] if "id" in item}

        # Both snapshots must expose the same element IDs — same live DOM, same session.
        # Any difference would indicate a session boundary was crossed between calls,
        # which would break the snapshot → click/type continuity contract.
        self.assertTrue(ids1, "snap1 must contain at least one element with an id")
        self.assertEqual(ids1, ids2, "element IDs must be stable across snapshots of the same live session")

    def test_browser_mcp_tools_run_fixture_interaction_loop(self) -> None:
        """
        Full continuity-chain contract test: snapshot → interact using snapshot IDs → verify effect.

        This test exercises the core continuity contract end-to-end:
        - snap1 provides element IDs from the live session
        - browser_click and browser_type are called with those IDs
        - snap2 and snap3 confirm the effects are visible in the same live session
        - browser_console confirms the live session accumulated console events

        The contract holds because all tool calls share the same persistent BrowserManager.
        If any tool call were routed to a new session, the element ID would be invalid
        (click/type would fail) or the DOM effects would not be visible in the next snapshot.
        """
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright not installed")

        fixture = Path(__file__).parent / "fixtures" / "browser" / "simple_page.html"
        url = fixture.resolve().as_uri()
        sm = build_codex_session_manager(model="gpt-5.4", enable_mcp_browser=True)

        opened = sm.tool_registry.get("browser_open").invoke(url=url)
        self.assertTrue(opened.ok, opened.content)

        # snap1: capture live element IDs for use in subsequent interactions.
        snap1 = sm.tool_registry.get("browser_snapshot").invoke()
        self.assertTrue(snap1.ok, snap1.content)
        elements1 = snap1.data["raw_result"]["structuredContent"]["elements"]
        button = next(item for item in elements1 if item["tag"] == "button")
        input_el = next(item for item in elements1 if item["tag"] == "input")

        # Click using the snap1 element ID — valid because the same live session is preserved.
        clicked = sm.tool_registry.get("browser_click").invoke(element_id=button["id"])
        self.assertTrue(clicked.ok, clicked.content)
        snap2 = sm.tool_registry.get("browser_snapshot").invoke()
        elements2 = snap2.data["raw_result"]["structuredContent"]["elements"]
        # Effect is visible in snap2 because it observes the same live DOM.
        self.assertTrue(any(item.get("text") == "Clicked!" for item in elements2))

        # Type using the snap1 input element ID — still valid; session not broken by the click.
        typed = sm.tool_registry.get("browser_type").invoke(element_id=input_el["id"], text="hello mcp")
        self.assertTrue(typed.ok, typed.content)
        snap3 = sm.tool_registry.get("browser_snapshot").invoke()
        elements3 = snap3.data["raw_result"]["structuredContent"]["elements"]
        self.assertTrue(any(item.get("text") == "hello mcp" for item in elements3))
        refreshed_input = next(item for item in elements3 if item["tag"] == "input")
        self.assertEqual(refreshed_input.get("value"), "hello mcp")

        # Console messages are accumulated across all tool calls in the same live session.
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
