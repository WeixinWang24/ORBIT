from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.tools.base import Tool, ToolResult
from orbit.tools.registry import ToolRegistry


class _FakeMcpTool(Tool):
    name = "git_status"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "path_exists"

    def __init__(self) -> None:
        self.tool_source = "mcp"
        self.server_name = "git"
        self.original_name = "git_status"
        self.descriptor = type(
            "Descriptor",
            (),
            {
                "description": "Return git status.",
                "input_schema": {"type": "object", "properties": {}},
            },
        )()

    def invoke(self, **kwargs) -> ToolResult:  # pragma: no cover
        return ToolResult(ok=True, content="unused")


class NativeToolIntrospectionTests(unittest.TestCase):
    def test_list_available_tools_includes_native_and_mcp_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            registry.register(_FakeMcpTool())

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            self.assertGreaterEqual(result.data["tool_count"], 1)
            tool_names = set(result.data["canonical_tool_names"])
            self.assertEqual(tool_names, set(result.data["tool_names"]))
            self.assertNotIn("native__list_available_tools", tool_names)
            self.assertNotIn("native__describe_tool", tool_names)
            self.assertIn("git_status", tool_names)
            git_group = next(group for group in result.data["servers"] if group["server_name"] == "git")
            self.assertEqual(git_group["tool_names"], ["git_status"])

    def test_list_available_tools_returns_full_inventory_without_input_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            registry.register(_FakeMcpTool())

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            self.assertNotIn("native__list_available_tools", result.data["tool_names"])
            self.assertNotIn("native__describe_tool", result.data["tool_names"])
            self.assertIn("git_status", result.data["tool_names"])

    def test_list_available_tools_includes_run_bash_in_full_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend
            backend = OpenAICodexExecutionBackend(workspace_root=Path(tmpdir))
            registry = backend._effective_tool_registry()

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            self.assertIn("run_bash", result.data["tool_names"])
            run_bash = next(tool for tool in result.data["tools"] if tool["name"] == "run_bash")
            self.assertIn("shell command", run_bash["use_when"].lower())
            self.assertEqual(run_bash["capability_family"], "shell_execution")

    def test_list_available_tools_returns_full_inventory_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            registry.register(_FakeMcpTool())

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            self.assertIn("tool_names", result.data)
            self.assertIn("canonical_tool_names", result.data)
            self.assertIn("tools", result.data)
            self.assertIn("inventory_excludes", result.data)
            self.assertIn("usage_guidance", result.data)
            self.assertIn("recommended_next_actions", result.data)
            self.assertIn("capability_families", result.data)
            self.assertIn("native__list_available_tools", result.data["inventory_excludes"])
            self.assertIn("native__describe_tool", result.data["inventory_excludes"])
            self.assertNotIn("native__list_available_tools", result.data["tool_names"])
            self.assertNotIn("native__describe_tool", result.data["tool_names"])
            self.assertTrue(all("purpose" in group for group in result.data["servers"]))
            self.assertTrue(all("when_to_use" in group for group in result.data["servers"]))
            self.assertEqual(result.data["canonical_tool_names"], result.data["tool_names"])
            self.assertTrue(all("callable_name" in tool for tool in result.data["tools"]))
            self.assertTrue(all("purpose_summary" in tool for tool in result.data["tools"]))
            self.assertTrue(all("use_when" in tool for tool in result.data["tools"]))
            self.assertTrue(all("capability_family" in tool for tool in result.data["tools"]))
            self.assertTrue(all("maturity" in tool for tool in result.data["tools"]))
            self.assertTrue(all("workflow_closure_status" in tool for tool in result.data["tools"]))
            self.assertTrue(all("known_limits" in tool for tool in result.data["tools"]))

    def test_list_available_tools_includes_capability_family_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))
            registry.register(_FakeMcpTool())

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            git_family = next(family for family in result.data["capability_families"] if family["family_name"] == "git_inspection")
            self.assertIn("git_status", git_family["tool_names"])
            self.assertIn("summary", git_family)
            self.assertIn("maturity", git_family)
            self.assertIn("workflow_closure_status", git_family)
            self.assertIn("known_limits", git_family)

    def test_real_registry_exposes_expected_capability_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend
            backend = OpenAICodexExecutionBackend(workspace_root=Path(tmpdir))
            registry = backend._effective_tool_registry()

            result = registry.get("native__list_available_tools").invoke()

            self.assertTrue(result.ok)
            families = {family["family_name"]: family for family in result.data["capability_families"]}
            self.assertIn("git_inspection", families)
            self.assertIn("git_mutation", families)
            self.assertIn("grounded_filesystem_mutation", families)
            self.assertIn("shell_execution", families)
            self.assertIn("process_lifecycle", families)

            self.assertIn("git_status", families["git_inspection"]["tool_names"])
            self.assertIn("git_commit", families["git_mutation"]["tool_names"])
            self.assertIn("apply_unified_patch", families["grounded_filesystem_mutation"]["tool_names"])
            self.assertIn("run_bash", families["shell_execution"]["tool_names"])
            self.assertIn("start_process", families["process_lifecycle"]["tool_names"])

            self.assertEqual(
                families["git_inspection"]["workflow_closure_status"],
                "closed_for_basic_repository_inspection",
            )
            self.assertEqual(
                families["git_mutation"]["workflow_closure_status"],
                "closed_for_basic_stage_restore_commit_and_existing_branch_checkout",
            )
            self.assertEqual(
                families["grounded_filesystem_mutation"]["workflow_closure_status"],
                "closed_for_grounded_single_file_exact_mutation_first_slice",
            )

    def test_describe_tool_returns_exact_tool_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))

            result = registry.get("native__describe_tool").invoke(name="native__read_file")

            self.assertTrue(result.ok)
            self.assertEqual(result.data["name"], "native__read_file")
            self.assertEqual(result.data["tool_source"], "native")
            self.assertEqual(result.data["side_effect_class"], "safe")
            self.assertFalse(result.data["requires_approval"])
            self.assertEqual(result.data["capability_family"], "native_filesystem_read")
            self.assertIn("family_summary", result.data)
            self.assertIn("status_note", result.data)
            self.assertIn("known_limits", result.data)

    def test_web_fetch_introspection_mentions_strict_ssl_and_failure_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend
            backend = OpenAICodexExecutionBackend(workspace_root=Path(tmpdir))
            registry = backend._effective_tool_registry()

            result = registry.get("native__describe_tool").invoke(name="web_fetch")

            self.assertTrue(result.ok)
            self.assertEqual(result.data["capability_family"], "web_retrieval")
            self.assertIn("strict certificate verification", result.data["status_note"])
            known_limits = " ".join(result.data["known_limits"])
            self.assertIn("strict SSL verification", known_limits)
            self.assertIn("SSL verification failures", known_limits)

    def test_describe_tool_fails_cleanly_for_missing_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry(Path(tmpdir))

            result = registry.get("native__describe_tool").invoke(name="does_not_exist")

            self.assertFalse(result.ok)
            self.assertIn("tool not found", result.content)


if __name__ == "__main__":
    unittest.main()
