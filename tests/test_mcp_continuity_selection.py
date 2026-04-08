from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orbit.runtime.mcp.models import McpClientBootstrap
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.tools.registry import ToolRegistry


class _FakeClient:
    """Minimal fake MCP client for continuity-selection tests."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    async def async_list_tools(self):
        return []

    def list_tools(self):
        return []

    async def async_call_tool(self, tool_name: str, arguments: dict):
        raise AssertionError("call_tool should not be reached in continuity-selection tests")

    def call_tool(self, tool_name: str, arguments: dict):
        raise AssertionError("call_tool should not be reached in continuity-selection tests")

    def list_resources(self):
        return []

    def read_resource(self, uri: str):
        return []

    def close(self) -> None:
        return None


class McpContinuitySelectionTests(unittest.TestCase):
    def _bootstrap(self, *, server_name: str, continuity_mode: str) -> McpClientBootstrap:
        return McpClientBootstrap(
            server_name=server_name,
            normalized_name=server_name,
            tool_prefix="",
            transport="stdio",
            command="fake-command",
            args=[],
            env={},
            continuity_mode=continuity_mode,
        )

    def test_stateless_mode_uses_build_mcp_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            stateless_client = _FakeClient(marker="stateless")

            with patch("orbit.runtime.mcp.registry_loader.build_mcp_client", return_value=stateless_client) as build_mock, \
                 patch("orbit.runtime.mcp.registry_loader.PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create") as persistent_mock:
                register_mcp_server_tools(
                    registry=registry,
                    bootstrap=self._bootstrap(server_name="filesystem", continuity_mode="stateless"),
                )

            build_mock.assert_called_once()
            persistent_mock.assert_not_called()

    def test_persistent_required_uses_persistent_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            persistent_client = _FakeClient(marker="persistent_required")

            with patch("orbit.runtime.mcp.registry_loader.build_mcp_client") as build_mock, \
                 patch(
                     "orbit.runtime.mcp.registry_loader.PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create",
                     return_value=persistent_client,
                 ) as persistent_mock:
                register_mcp_server_tools(
                    registry=registry,
                    bootstrap=self._bootstrap(server_name="browser", continuity_mode="persistent_required"),
                )

            persistent_mock.assert_called_once()
            build_mock.assert_not_called()

    def test_persistent_preferred_currently_uses_persistent_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            persistent_client = _FakeClient(marker="persistent_preferred")

            with patch("orbit.runtime.mcp.registry_loader.build_mcp_client") as build_mock, \
                 patch(
                     "orbit.runtime.mcp.registry_loader.PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create",
                     return_value=persistent_client,
                 ) as persistent_mock:
                register_mcp_server_tools(
                    registry=registry,
                    bootstrap=self._bootstrap(server_name="process", continuity_mode="persistent_preferred"),
                )

            persistent_mock.assert_called_once()
            build_mock.assert_not_called()

    def test_selection_depends_on_continuity_mode_not_server_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            persistent_client = _FakeClient(marker="persistent_process")

            with patch("orbit.runtime.mcp.registry_loader.build_mcp_client") as build_mock, \
                 patch(
                     "orbit.runtime.mcp.registry_loader.PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create",
                     return_value=persistent_client,
                 ) as persistent_mock:
                register_mcp_server_tools(
                    registry=registry,
                    bootstrap=self._bootstrap(server_name="process", continuity_mode="persistent_preferred"),
                )

            persistent_mock.assert_called_once()
            build_mock.assert_not_called()

    def test_browser_name_alone_no_longer_forces_persistent_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            stateless_client = _FakeClient(marker="browser_but_stateless")

            with patch("orbit.runtime.mcp.registry_loader.build_mcp_client", return_value=stateless_client) as build_mock, \
                 patch("orbit.runtime.mcp.registry_loader.PERSISTENT_MCP_CLIENT_REGISTRY.get_or_create") as persistent_mock:
                register_mcp_server_tools(
                    registry=registry,
                    bootstrap=self._bootstrap(server_name="browser", continuity_mode="stateless"),
                )

            build_mock.assert_called_once()
            persistent_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
