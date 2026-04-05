from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend


class OpenAICodexToolRegistryTests(unittest.TestCase):
    def test_effective_tool_registry_includes_bash_and_process_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenAICodexExecutionBackend(workspace_root=Path(tmpdir))
            registry = backend._effective_tool_registry()
            names = {tool.name for tool in registry.list_tools()}
            self.assertIn("run_bash", names)
            self.assertIn("start_process", names)
            self.assertIn("read_process_output", names)
            self.assertIn("wait_process", names)
            self.assertIn("terminate_process", names)


if __name__ == "__main__":
    unittest.main()
