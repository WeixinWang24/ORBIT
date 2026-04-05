from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend


class OpenAICodexToolSchemaAlignmentTests(unittest.TestCase):
    def test_build_tool_definitions_matches_registry_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenAICodexExecutionBackend(workspace_root=Path(tmpdir))
            registry = backend._effective_tool_registry()
            schema = backend.build_tool_definitions()
            registry_names = {tool.name for tool in registry.list_tools()}
            schema_names = {item["name"] for item in schema}

            self.assertEqual(schema_names, registry_names)
            self.assertIn("run_bash", schema_names)
            self.assertIn("git_changed_files", schema_names)
            self.assertIn("git_unstage", schema_names)
            self.assertIn("native__write_file", schema_names)
            self.assertIn("apply_unified_patch", schema_names)
            self.assertIn("web_fetch", schema_names)
            self.assertIn("todo_read", schema_names)
            self.assertIn("todo_write", schema_names)


if __name__ == "__main__":
    unittest.main()
