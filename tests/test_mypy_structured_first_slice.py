from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from mcp_servers.system.core.mypy.stdio_server import (
    classify_mypy_outcome,
    invoke_mypy,
    _parse_mypy_issue_line,
)


class TestParseMypyIssueLine(unittest.TestCase):
    def test_parses_error_line_with_code(self):
        issue = _parse_mypy_issue_line(
            'src/foo.py:12: error: Incompatible return value type (got "int", expected "str")  [return-value]'
        )
        self.assertIsNotNone(issue)
        self.assertEqual(issue["path"], "src/foo.py")
        self.assertEqual(issue["line"], 12)
        self.assertIsNone(issue["column"])
        self.assertEqual(issue["severity"], "error")
        self.assertEqual(issue["error_code"], "return-value")

    def test_parses_note_line(self):
        issue = _parse_mypy_issue_line('src/foo.py:12: note: Revealed type is "builtins.int"')
        self.assertIsNotNone(issue)
        self.assertEqual(issue["severity"], "note")
        self.assertIsNone(issue["error_code"])

    def test_parses_line_with_column(self):
        issue = _parse_mypy_issue_line('src/foo.py:12:5: error: Something bad  [misc]')
        self.assertIsNotNone(issue)
        self.assertEqual(issue["column"], 5)
        self.assertEqual(issue["error_code"], "misc")

    def test_malformed_line_returns_none(self):
        self.assertIsNone(_parse_mypy_issue_line('not a mypy issue line'))


class TestClassifyMypyOutcome(unittest.TestCase):
    def test_passed(self):
        result = classify_mypy_outcome(exit_code=0, timed_out=False, issues_total=0, raw_output="")
        self.assertTrue(result["success"])
        self.assertEqual(result["outcome_kind"], "passed")
        self.assertEqual(result["failure_layer"], "none")
        self.assertEqual(result["failure_kind"], "none")

    def test_issues_found(self):
        result = classify_mypy_outcome(exit_code=1, timed_out=False, issues_total=2, raw_output="")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "issues_found")
        self.assertEqual(result["failure_layer"], "type_analysis")
        self.assertEqual(result["failure_kind"], "type_errors")

    def test_timeout(self):
        result = classify_mypy_outcome(exit_code=None, timed_out=True, issues_total=0, raw_output="")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "timeout")
        self.assertEqual(result["failure_layer"], "runtime_execution")
        self.assertEqual(result["failure_kind"], "timeout")

    def test_usage_error(self):
        result = classify_mypy_outcome(exit_code=2, timed_out=False, issues_total=0, raw_output="")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "usage_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "usage_error")

    def test_tool_error(self):
        result = classify_mypy_outcome(exit_code=9, timed_out=False, issues_total=0, raw_output="boom")
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "tool_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "mypy_execution_error")


class TestInvokeMypyIntegration(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orbit_mypy_test_")
        if shutil.which("mypy") is None:
            self.skipTest("mypy not installed in current environment")

    def _write_file(self, name: str, content: str) -> Path:
        path = Path(self._tmpdir) / name
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def test_pass_case(self):
        self._write_file("ok.py", 'def returns_str() -> str:\n    return "ok"\n')
        result = invoke_mypy(workspace_root=Path(self._tmpdir), paths=["ok.py"])
        self.assertEqual(result["result_kind"], "mypy_structured")
        self.assertEqual(result["diagnostic_kind"], "type_analysis")
        self.assertIn(result["outcome_kind"], {"passed", "issues_found", "tool_error", "usage_error", "timeout"})
        self.assertIn("invocation", result)
        self.assertIn("workspace_root", result["invocation"])
        self.assertIn("timeout_seconds", result["invocation"])
        self.assertIn("selection_basis", result["invocation"])

    def test_issue_case(self):
        self._write_file("bad.py", 'def returns_str() -> str:\n    return 1\n')
        result = invoke_mypy(workspace_root=Path(self._tmpdir), paths=["bad.py"])
        self.assertEqual(result["result_kind"], "mypy_structured")
        self.assertEqual(result["diagnostic_kind"], "type_analysis")
        self.assertIn("issues", result)
        self.assertIn("issues_total", result)
        self.assertIn("issues_truncated", result)


if __name__ == "__main__":
    unittest.main()
