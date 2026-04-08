from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from mcp_servers.system.core.ruff.stdio_server import (
    MAX_ISSUES_RETURNED,
    classify_ruff_outcome,
    invoke_ruff,
    _normalize_ruff_issue,
)


_SAMPLE_RUFF_ITEM = {
    "filename": "/tmp/example.py",
    "location": {"row": 1, "column": 8},
    "end_location": {"row": 1, "column": 10},
    "code": "F401",
    "message": "`os` imported but unused",
}


class TestNormalizeRuffIssue(unittest.TestCase):
    def test_normalizes_basic_issue_shape(self):
        issue = _normalize_ruff_issue(_SAMPLE_RUFF_ITEM)
        self.assertEqual(issue["path"], "/tmp/example.py")
        self.assertEqual(issue["line"], 1)
        self.assertEqual(issue["column"], 8)
        self.assertEqual(issue["end_line"], 1)
        self.assertEqual(issue["end_column"], 10)
        self.assertEqual(issue["code"], "F401")
        self.assertEqual(issue["message"], "`os` imported but unused")
        self.assertEqual(issue["severity"], "error")
        self.assertEqual(issue["rule_family"], "F")


class TestClassifyRuffOutcome(unittest.TestCase):
    def test_passed(self):
        result = classify_ruff_outcome(exit_code=0, timed_out=False, issues_total=0, raw_output="")
        self.assertTrue(result["success"])
        self.assertEqual(result["outcome_kind"], "passed")
        self.assertEqual(result["failure_layer"], "none")
        self.assertEqual(result["failure_kind"], "none")

    def test_issues_found(self):
        result = classify_ruff_outcome(exit_code=1, timed_out=False, issues_total=3, raw_output="[]")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "issues_found")
        self.assertEqual(result["failure_layer"], "static_analysis")
        self.assertEqual(result["failure_kind"], "lint_findings")

    def test_timeout(self):
        result = classify_ruff_outcome(exit_code=None, timed_out=True, issues_total=0, raw_output="")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "timeout")
        self.assertEqual(result["failure_layer"], "runtime_execution")
        self.assertEqual(result["failure_kind"], "timeout")

    def test_usage_error(self):
        result = classify_ruff_outcome(exit_code=2, timed_out=False, issues_total=0, raw_output="")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "usage_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "usage_error")

    def test_tool_error(self):
        result = classify_ruff_outcome(exit_code=9, timed_out=False, issues_total=0, raw_output="boom")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "tool_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "ruff_execution_error")


class TestInvokeRuffIntegration(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orbit_ruff_test_")
        if shutil.which("ruff") is None:
            self.skipTest("ruff not installed in current environment")

    def _write_file(self, name: str, content: str) -> Path:
        path = Path(self._tmpdir) / name
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def test_pass_case(self):
        self._write_file("ok.py", "x = 1\n")
        result = invoke_ruff(workspace_root=Path(self._tmpdir))
        self.assertEqual(result["result_kind"], "ruff_structured")
        self.assertEqual(result["diagnostic_kind"], "static_analysis")
        self.assertIn(result["outcome_kind"], {"passed", "issues_found", "tool_error", "usage_error", "timeout"})
        self.assertIn("invocation", result)
        self.assertIn("workspace_root", result["invocation"])
        self.assertIn("timeout_seconds", result["invocation"])
        self.assertIn("selection_basis", result["invocation"])

    def test_issue_case(self):
        self._write_file("bad.py", "import os\n")
        result = invoke_ruff(workspace_root=Path(self._tmpdir))
        self.assertEqual(result["result_kind"], "ruff_structured")
        self.assertEqual(result["diagnostic_kind"], "static_analysis")
        self.assertIn("issues", result)
        self.assertIn("issues_total", result)
        self.assertIn("issues_truncated", result)
        self.assertLessEqual(len(result["issues"]), MAX_ISSUES_RETURNED)


if __name__ == "__main__":
    unittest.main()
