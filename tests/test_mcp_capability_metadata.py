"""
MCP capability metadata first-slice tests.

Covers:
- Each bootstrap function returns the correct McpCapabilityMetadata
- Metadata propagates through McpClientBootstrap (bootstrap-level visibility)
- Metadata propagates to McpToolWrapper (registry-visible layer)
- McpCapabilityMetadata is frozen (immutable after construction)
- bootstrap_stdio_mcp_server passes capability_metadata through correctly
- Servers without metadata declared (e.g., obsidian) yield None gracefully
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orbit.runtime.mcp.models import McpCapabilityMetadata, McpClientBootstrap, McpStdioServerConfig
from orbit.runtime.mcp.bootstrap import bootstrap_stdio_mcp_server


WORKSPACE = str(Path(__file__).resolve().parents[1])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bootstrap_with_metadata(metadata: McpCapabilityMetadata) -> McpClientBootstrap:
    config = McpStdioServerConfig(
        name="test_server",
        command="fake-cmd",
        capability_metadata=metadata,
    )
    return bootstrap_stdio_mcp_server(config)


def _make_fake_client(bootstrap: McpClientBootstrap):
    """Minimal fake client that exposes the bootstrap (mirrors StdioMcpClient)."""
    class _FakeClient:
        def __init__(self) -> None:
            self.bootstrap = bootstrap

        async def async_list_tools(self):
            return []

        def list_tools(self):
            return []

        async def async_call_tool(self, tool_name, arguments):
            raise AssertionError("not expected in metadata tests")

        def call_tool(self, tool_name, arguments):
            raise AssertionError("not expected in metadata tests")

        def list_resources(self):
            return []

        def read_resource(self, uri):
            return []

        def close(self):
            return None

    return _FakeClient()


# ---------------------------------------------------------------------------
# A. Bootstrap output contains correct metadata
# ---------------------------------------------------------------------------

class BootstrapMetadataDeclarationTests(unittest.TestCase):

    def _assert_metadata(self, bootstrap: McpClientBootstrap, **expected_fields) -> None:
        meta = bootstrap.capability_metadata
        self.assertIsNotNone(meta, f"{bootstrap.server_name} bootstrap must declare capability_metadata")
        for field, expected in expected_fields.items():
            self.assertEqual(
                getattr(meta, field), expected,
                f"{bootstrap.server_name}.{field}: expected {expected!r}, got {getattr(meta, field)!r}",
            )

    def test_browser_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.browser_bootstrap import bootstrap_local_browser_mcp_server
        b = bootstrap_local_browser_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="browser",
            continuity_type="live_host",
            truth_source="live_host_state",
            layer_role="substrate",
            transport_importance="required",
        )

    def test_process_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
        b = bootstrap_local_process_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="process",
            continuity_type="persisted_task",
            truth_source="persisted_runtime_artifacts",
            layer_role="substrate",
            transport_importance="preferred",
        )

    def test_pytest_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.pytest_bootstrap import bootstrap_local_pytest_mcp_server
        b = bootstrap_local_pytest_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="diagnostics",
            continuity_type="bounded_result",
            truth_source="bounded_result_object",
            layer_role="interpretation",
            transport_importance="irrelevant",
        )

    def test_ruff_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.ruff_bootstrap import bootstrap_local_ruff_mcp_server
        b = bootstrap_local_ruff_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="diagnostics",
            continuity_type="bounded_result",
            truth_source="bounded_result_object",
            layer_role="interpretation",
            transport_importance="irrelevant",
        )

    def test_mypy_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.mypy_bootstrap import bootstrap_local_mypy_mcp_server
        b = bootstrap_local_mypy_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="diagnostics",
            continuity_type="bounded_result",
            truth_source="bounded_result_object",
            layer_role="interpretation",
            transport_importance="irrelevant",
        )

    def test_filesystem_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.bootstrap import bootstrap_local_filesystem_mcp_server
        b = bootstrap_local_filesystem_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="filesystem",
            # stateless: workspace root is injected as startup config (env var), not
            # maintained as live session state. Truth comes from the underlying filesystem.
            continuity_type="stateless",
            truth_source="filesystem_or_repo_truth",
            layer_role="substrate",
            transport_importance="irrelevant",
        )

    def test_git_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.bootstrap import bootstrap_local_git_mcp_server
        b = bootstrap_local_git_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="git",
            continuity_type="stateless",
            truth_source="filesystem_or_repo_truth",
            layer_role="access_support",
            transport_importance="irrelevant",
        )

    def test_bash_bootstrap_metadata(self) -> None:
        from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
        b = bootstrap_local_bash_mcp_server(workspace_root=WORKSPACE)
        self._assert_metadata(
            b,
            capability_family="bash",
            continuity_type="stateless",
            truth_source="bounded_result_object",
            layer_role="access_support",
            transport_importance="irrelevant",
        )

    def test_diagnostics_families_share_identical_posture(self) -> None:
        """pytest, ruff, and mypy must all declare the same diagnostics posture."""
        from orbit.runtime.mcp.pytest_bootstrap import bootstrap_local_pytest_mcp_server
        from orbit.runtime.mcp.ruff_bootstrap import bootstrap_local_ruff_mcp_server
        from orbit.runtime.mcp.mypy_bootstrap import bootstrap_local_mypy_mcp_server

        pytest_meta = bootstrap_local_pytest_mcp_server(workspace_root=WORKSPACE).capability_metadata
        ruff_meta = bootstrap_local_ruff_mcp_server(workspace_root=WORKSPACE).capability_metadata
        mypy_meta = bootstrap_local_mypy_mcp_server(workspace_root=WORKSPACE).capability_metadata

        # All three share the same posture values (family, continuity, truth, role, transport).
        self.assertEqual(pytest_meta, ruff_meta)
        self.assertEqual(ruff_meta, mypy_meta)


# ---------------------------------------------------------------------------
# B. bootstrap_stdio_mcp_server propagates capability_metadata
# ---------------------------------------------------------------------------

class BootstrapStdioPassthroughTests(unittest.TestCase):

    def test_metadata_propagates_from_config_to_bootstrap(self) -> None:
        metadata = McpCapabilityMetadata(
            capability_family="bash",
            continuity_type="stateless",
            truth_source="bounded_result_object",
            layer_role="access_support",
            transport_importance="irrelevant",
        )
        bootstrap = _make_bootstrap_with_metadata(metadata)
        self.assertIs(bootstrap.capability_metadata, metadata)

    def test_none_metadata_propagates_gracefully(self) -> None:
        config = McpStdioServerConfig(name="obsidian", command="fake-cmd")
        bootstrap = bootstrap_stdio_mcp_server(config)
        self.assertIsNone(bootstrap.capability_metadata)


# ---------------------------------------------------------------------------
# C. Metadata propagates to McpToolWrapper (registry-visible layer)
# ---------------------------------------------------------------------------

class McpToolWrapperMetadataPropagationTests(unittest.TestCase):

    def _make_wrapper(self, metadata: McpCapabilityMetadata | None):
        """Build a McpToolWrapper using a fake client that carries the given metadata."""
        from orbit.runtime.mcp.models import McpToolDescriptor
        from orbit.tools.mcp import McpToolWrapper

        bootstrap = McpClientBootstrap(
            server_name="test",
            normalized_name="test",
            tool_prefix="",
            transport="stdio",
            command="fake-cmd",
            capability_metadata=metadata,
        )
        descriptor = McpToolDescriptor(
            server_name="test",
            original_name="test_tool",
            orbit_tool_name="test_tool",
        )
        client = _make_fake_client(bootstrap)
        return McpToolWrapper(descriptor=descriptor, client=client)

    def test_capability_metadata_visible_on_wrapper(self) -> None:
        metadata = McpCapabilityMetadata(
            capability_family="process",
            continuity_type="persisted_task",
            truth_source="persisted_runtime_artifacts",
            layer_role="substrate",
            transport_importance="preferred",
        )
        wrapper = self._make_wrapper(metadata)
        self.assertIsNotNone(wrapper.capability_metadata)
        self.assertEqual(wrapper.capability_metadata.capability_family, "process")
        self.assertEqual(wrapper.capability_metadata.continuity_type, "persisted_task")
        self.assertEqual(wrapper.capability_metadata.truth_source, "persisted_runtime_artifacts")
        self.assertEqual(wrapper.capability_metadata.layer_role, "substrate")
        self.assertEqual(wrapper.capability_metadata.transport_importance, "preferred")

    def test_wrapper_capability_metadata_is_same_object_as_bootstrap(self) -> None:
        """Metadata must not be copied or reconstructed — it must be the same object."""
        metadata = McpCapabilityMetadata(
            capability_family="browser",
            continuity_type="live_host",
            truth_source="live_host_state",
            layer_role="substrate",
            transport_importance="required",
        )
        wrapper = self._make_wrapper(metadata)
        self.assertIs(wrapper.capability_metadata, metadata)

    def test_wrapper_capability_metadata_is_none_when_not_declared(self) -> None:
        wrapper = self._make_wrapper(None)
        self.assertIsNone(wrapper.capability_metadata)

    def test_wrapper_metadata_for_real_browser_bootstrap(self) -> None:
        """End-to-end: real browser bootstrap → wrapper carries correct metadata."""
        from orbit.runtime.mcp.browser_bootstrap import bootstrap_local_browser_mcp_server
        from orbit.runtime.mcp.models import McpToolDescriptor
        from orbit.tools.mcp import McpToolWrapper

        bootstrap = bootstrap_local_browser_mcp_server(workspace_root=WORKSPACE)
        descriptor = McpToolDescriptor(
            server_name="browser",
            original_name="navigate",
            orbit_tool_name="navigate",
        )
        client = _make_fake_client(bootstrap)
        wrapper = McpToolWrapper(descriptor=descriptor, client=client)
        self.assertIsNotNone(wrapper.capability_metadata)
        self.assertEqual(wrapper.capability_metadata.capability_family, "browser")
        self.assertEqual(wrapper.capability_metadata.transport_importance, "required")

    def test_wrapper_metadata_for_real_process_bootstrap(self) -> None:
        """End-to-end: real process bootstrap → wrapper carries correct metadata."""
        from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
        from orbit.runtime.mcp.models import McpToolDescriptor
        from orbit.tools.mcp import McpToolWrapper

        bootstrap = bootstrap_local_process_mcp_server(workspace_root=WORKSPACE)
        descriptor = McpToolDescriptor(
            server_name="process",
            original_name="start_process",
            orbit_tool_name="start_process",
        )
        client = _make_fake_client(bootstrap)
        wrapper = McpToolWrapper(descriptor=descriptor, client=client)
        self.assertIsNotNone(wrapper.capability_metadata)
        self.assertEqual(wrapper.capability_metadata.capability_family, "process")
        self.assertEqual(wrapper.capability_metadata.transport_importance, "preferred")


# ---------------------------------------------------------------------------
# D. McpCapabilityMetadata structural invariants
# ---------------------------------------------------------------------------

class McpCapabilityMetadataInvariantTests(unittest.TestCase):

    def test_metadata_is_frozen(self) -> None:
        """McpCapabilityMetadata must be immutable after construction."""
        meta = McpCapabilityMetadata(
            capability_family="bash",
            continuity_type="stateless",
            truth_source="bounded_result_object",
            layer_role="access_support",
            transport_importance="irrelevant",
        )
        with self.assertRaises((AttributeError, TypeError)):
            meta.capability_family = "browser"  # type: ignore[misc]

    def test_equal_metadata_objects_are_equal(self) -> None:
        a = McpCapabilityMetadata(
            capability_family="diagnostics",
            continuity_type="bounded_result",
            truth_source="bounded_result_object",
            layer_role="interpretation",
            transport_importance="irrelevant",
        )
        b = McpCapabilityMetadata(
            capability_family="diagnostics",
            continuity_type="bounded_result",
            truth_source="bounded_result_object",
            layer_role="interpretation",
            transport_importance="irrelevant",
        )
        self.assertEqual(a, b)

    def test_distinct_metadata_objects_are_not_equal(self) -> None:
        browser = McpCapabilityMetadata(
            capability_family="browser",
            continuity_type="live_host",
            truth_source="live_host_state",
            layer_role="substrate",
            transport_importance="required",
        )
        process = McpCapabilityMetadata(
            capability_family="process",
            continuity_type="persisted_task",
            truth_source="persisted_runtime_artifacts",
            layer_role="substrate",
            transport_importance="preferred",
        )
        self.assertNotEqual(browser, process)


if __name__ == "__main__":
    unittest.main()
