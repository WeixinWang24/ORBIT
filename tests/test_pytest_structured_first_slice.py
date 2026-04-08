"""
Tests for ORBIT's run_pytest_structured first slice.

Coverage:
- Parser unit tests (parse_collected, parse_summary_counts, parse_short_summary_items,
  parse_failure_blocks, build_failure_records, parse_pytest_output)
- invoke_pytest integration tests using real temp-dir test files
- Bounded output / truncation behavior
- Timeout behavior
- Best-effort / honest parse_confidence signalling
- Result shape stability (all callers can rely on these fields being present)
"""
from __future__ import annotations

import sys
import textwrap
import time
import unittest
from pathlib import Path

import tempfile

# Import server-level functions directly for unit testing.
# These are importable without the MCP server running.
from mcp_servers.system.core.pytest.stdio_server import (
    MAX_EXCERPT_CHARS,
    MAX_FAILURES_RETURNED,
    MAX_RAW_OUTPUT_CHARS,
    build_failure_records,
    invoke_pytest,
    parse_collected,
    parse_failure_blocks,
    parse_pytest_output,
    parse_short_summary_items,
    parse_summary_counts,
    _sanitize_targets,
    _resolve_test_scope,
)


# ─── Sample pytest output fixtures ───────────────────────────────────────────

_ALL_PASS_OUTPUT = """\
collected 3 items

tests/test_foo.py::test_a PASSED                                         [ 33%]
tests/test_foo.py::test_b PASSED                                         [ 66%]
tests/test_foo.py::test_c PASSED                                         [100%]

=========================== 3 passed in 0.04s ==============================
"""

_ONE_FAIL_OUTPUT = """\
collected 2 items

tests/test_foo.py::test_pass PASSED                                      [ 50%]
tests/test_foo.py::test_fail FAILED                                      [100%]

=================================== FAILURES ===================================
_________________________________ test_fail __________________________________

    def test_fail():
>       assert 1 == 2
E       AssertionError: assert 1 == 2

tests/test_foo.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_foo.py::test_fail - AssertionError: assert 1 == 2
========================= 1 failed, 1 passed in 0.05s ==========================
"""

_TWO_FAIL_OUTPUT = """\
collected 3 items

tests/test_foo.py::test_pass PASSED                                      [ 33%]
tests/test_foo.py::test_fail1 FAILED                                     [ 66%]
tests/test_foo.py::test_fail2 FAILED                                     [100%]

=================================== FAILURES ===================================
________________________________ test_fail1 __________________________________

    def test_fail1():
>       assert "a" == "b"
E       AssertionError: assert 'a' == 'b'

tests/test_foo.py:8: AssertionError
________________________________ test_fail2 __________________________________

    def test_fail2():
>       raise ValueError("bad value")
E       ValueError: bad value

tests/test_foo.py:12: ValueError
=========================== short test summary info ============================
FAILED tests/test_foo.py::test_fail1 - AssertionError: assert 'a' == 'b'
FAILED tests/test_foo.py::test_fail2 - ValueError: bad value
=================== 2 failed, 1 passed in 0.06s ====================
"""

_NO_TESTS_OUTPUT = """\
collected 0 items

========================= no tests ran in 0.01s ==========================
"""

_INTERNAL_ERROR_OUTPUT = """\
INTERNALERROR> Traceback (most recent call last):
  ...
INTERNALERROR> SomeError: something broke internally
"""


# ─── Parser unit tests ───────────────────────────────────────────────────────

class TestParseCollected(unittest.TestCase):
    def test_extracts_count(self):
        self.assertEqual(parse_collected("collected 5 items"), 5)

    def test_extracts_single_item(self):
        self.assertEqual(parse_collected("collected 1 item"), 1)

    def test_returns_none_when_missing(self):
        self.assertIsNone(parse_collected("no collection line here"))

    def test_extracts_from_realistic_output(self):
        self.assertEqual(parse_collected(_ALL_PASS_OUTPUT), 3)


class TestParseSummaryCounts(unittest.TestCase):
    def test_all_pass(self):
        counts = parse_summary_counts(_ALL_PASS_OUTPUT)
        self.assertEqual(counts["passed"], 3)
        self.assertIsNone(counts["failed"])
        self.assertIsNotNone(counts["duration_seconds"])

    def test_one_fail(self):
        counts = parse_summary_counts(_ONE_FAIL_OUTPUT)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["passed"], 1)

    def test_two_fail(self):
        counts = parse_summary_counts(_TWO_FAIL_OUTPUT)
        self.assertEqual(counts["failed"], 2)
        self.assertEqual(counts["passed"], 1)

    def test_no_tests_ran(self):
        counts = parse_summary_counts(_NO_TESTS_OUTPUT)
        # "no tests ran" line may not have counts — all None is acceptable
        self.assertIsNotNone(counts)

    def test_duration_parsed(self):
        counts = parse_summary_counts(_ONE_FAIL_OUTPUT)
        self.assertIsInstance(counts["duration_seconds"], float)
        self.assertGreater(counts["duration_seconds"], 0)

    def test_returns_none_fields_for_missing(self):
        counts = parse_summary_counts("no summary line here")
        for k in ("passed", "failed", "skipped", "errors", "warnings"):
            self.assertIsNone(counts[k])


class TestParseShortSummaryItems(unittest.TestCase):
    def test_one_failure(self):
        items = parse_short_summary_items(_ONE_FAIL_OUTPUT)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "FAILED")
        self.assertEqual(items[0]["node_id"], "tests/test_foo.py::test_fail")
        self.assertIn("AssertionError", items[0]["reason"])

    def test_two_failures(self):
        items = parse_short_summary_items(_TWO_FAIL_OUTPUT)
        self.assertEqual(len(items), 2)
        node_ids = [i["node_id"] for i in items]
        self.assertIn("tests/test_foo.py::test_fail1", node_ids)
        self.assertIn("tests/test_foo.py::test_fail2", node_ids)

    def test_all_pass_returns_empty(self):
        items = parse_short_summary_items(_ALL_PASS_OUTPUT)
        self.assertEqual(items, [])

    def test_no_duplicate_node_ids(self):
        # Inject a duplicate and verify deduplication
        output = _ONE_FAIL_OUTPUT + "\nFAILED tests/test_foo.py::test_fail - same error\n"
        items = parse_short_summary_items(output)
        node_ids = [i["node_id"] for i in items]
        self.assertEqual(len(node_ids), len(set(node_ids)))


class TestParseFailureBlocks(unittest.TestCase):
    def test_extracts_one_block(self):
        blocks = parse_failure_blocks(_ONE_FAIL_OUTPUT)
        self.assertIn("test_fail", blocks)
        self.assertIn("AssertionError", blocks["test_fail"])

    def test_extracts_two_blocks(self):
        blocks = parse_failure_blocks(_TWO_FAIL_OUTPUT)
        self.assertTrue(any("test_fail1" in k for k in blocks))
        self.assertTrue(any("test_fail2" in k for k in blocks))

    def test_no_blocks_for_passing_run(self):
        blocks = parse_failure_blocks(_ALL_PASS_OUTPUT)
        self.assertEqual(blocks, {})


class TestBuildFailureRecords(unittest.TestCase):
    def test_combines_short_items_with_blocks(self):
        short_items = [
            {"status": "FAILED", "node_id": "tests/test_foo.py::test_fail", "reason": "AssertionError: 1 == 2"}
        ]
        blocks = {"test_fail": "some traceback content"}
        records, truncated = build_failure_records(short_items, blocks)
        self.assertEqual(len(records), 1)
        self.assertFalse(truncated)
        self.assertEqual(records[0]["node_id"], "tests/test_foo.py::test_fail")
        self.assertEqual(records[0]["headline"], "AssertionError: 1 == 2")
        self.assertIn("traceback", records[0]["excerpt"])

    def test_truncates_at_max_failures(self):
        short_items = [
            {"status": "FAILED", "node_id": f"tests/test_foo.py::test_{i}", "reason": f"err_{i}"}
            for i in range(MAX_FAILURES_RETURNED + 5)
        ]
        records, truncated = build_failure_records(short_items, {})
        self.assertEqual(len(records), MAX_FAILURES_RETURNED)
        self.assertTrue(truncated)

    def test_excerpt_truncated_at_max_chars(self):
        short_items = [{"status": "FAILED", "node_id": "tests/test_foo.py::test_x", "reason": "err"}]
        long_body = "x" * (MAX_EXCERPT_CHARS + 100)
        blocks = {"test_x": long_body}
        records, _ = build_failure_records(short_items, blocks, max_excerpt_chars=MAX_EXCERPT_CHARS)
        self.assertEqual(len(records[0]["excerpt"]), MAX_EXCERPT_CHARS)
        self.assertTrue(records[0]["excerpt_truncated"])

    def test_empty_excerpt_when_no_block(self):
        short_items = [{"status": "FAILED", "node_id": "tests/test_foo.py::test_missing", "reason": "err"}]
        records, _ = build_failure_records(short_items, {})
        self.assertEqual(records[0]["excerpt"], "")
        self.assertFalse(records[0]["excerpt_truncated"])


class TestParsePytestOutput(unittest.TestCase):
    def test_all_pass_result(self):
        result = parse_pytest_output(_ALL_PASS_OUTPUT, "", exit_code=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["failures_total"], 0)
        self.assertFalse(result["failures_truncated"])
        self.assertEqual(result["counts"]["passed"], 3)
        self.assertEqual(result["result_kind"], "pytest_structured")
        self.assertEqual(result["diagnostic_kind"], "test_execution")
        self.assertEqual(result["outcome_kind"], "passed")
        self.assertEqual(result["failure_layer"], "none")
        self.assertEqual(result["failure_kind"], "none")
        self.assertIn(result["parse_confidence"], {"full", "partial", "minimal"})

    def test_one_fail_result(self):
        result = parse_pytest_output(_ONE_FAIL_OUTPUT, "", exit_code=1)
        self.assertFalse(result["success"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["failures_total"], 1)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["outcome_kind"], "failed")
        self.assertEqual(result["failure_layer"], "test_execution")
        self.assertEqual(result["failure_kind"], "assertion_failures")
        self.assertEqual(result["failures"][0]["status"], "FAILED")
        self.assertEqual(result["failures"][0]["node_id"], "tests/test_foo.py::test_fail")
        self.assertIn("AssertionError", result["failures"][0]["headline"])

    def test_timed_out_result(self):
        result = parse_pytest_output("", "", exit_code=None, timed_out=True)
        self.assertFalse(result["success"])
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["exit_code"])
        self.assertEqual(result["outcome_kind"], "timeout")
        self.assertEqual(result["failure_layer"], "runtime_execution")
        self.assertEqual(result["failure_kind"], "timeout")

    def test_no_tests_collected(self):
        result = parse_pytest_output(_NO_TESTS_OUTPUT, "", exit_code=5)
        # No tests collected is not a failure
        self.assertTrue(result["success"])
        self.assertEqual(result["outcome_kind"], "no_tests_collected")
        self.assertEqual(result["failure_layer"], "none")
        self.assertEqual(result["failure_kind"], "none")

    def test_result_shape_stability(self):
        """All expected fields must always be present regardless of output content."""
        for output, code in [
            (_ALL_PASS_OUTPUT, 0),
            (_ONE_FAIL_OUTPUT, 1),
            (_NO_TESTS_OUTPUT, 5),
            ("garbage output\n", 1),
            ("", 3),
        ]:
            result = parse_pytest_output(output, "", exit_code=code)
            required_fields = {
                "result_kind", "diagnostic_kind", "outcome_kind", "failure_layer", "failure_kind",
                "success", "exit_code", "timed_out",
                "failures", "failures_truncated", "failures_total",
                "raw_output_excerpt", "raw_output_truncated",
                "parse_confidence",
            }
            for field in required_fields:
                self.assertIn(field, result, f"field {field!r} missing for exit_code={code}")
            self.assertEqual(result["result_kind"], "pytest_structured")
            self.assertEqual(result["diagnostic_kind"], "test_execution")
            # counts sub-dict
            self.assertIn("counts", result)
            count_fields = {"collected", "passed", "failed", "skipped", "errors", "warnings", "duration_seconds"}
            for f in count_fields:
                self.assertIn(f, result["counts"])

    def test_parse_confidence_is_valid_value(self):
        for output, code in [(_ALL_PASS_OUTPUT, 0), (_ONE_FAIL_OUTPUT, 1), ("garbage", 1)]:
            result = parse_pytest_output(output, "", exit_code=code)
            self.assertIn(result["parse_confidence"], {"full", "partial", "minimal"})

    def test_usage_error_classification(self):
        result = parse_pytest_output("usage error", "", exit_code=4)
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "usage_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "usage_error")

    def test_raw_output_truncated(self):
        large_output = "x\n" * (MAX_RAW_OUTPUT_CHARS + 1000)
        result = parse_pytest_output(large_output, "", exit_code=0)
        self.assertLessEqual(len(result["raw_output_excerpt"]), MAX_RAW_OUTPUT_CHARS)
        self.assertTrue(result["raw_output_truncated"])

    def test_internal_error_output(self):
        result = parse_pytest_output(_INTERNAL_ERROR_OUTPUT, "", exit_code=3)
        # Internal error = not success; parse_confidence should not claim "full"
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "internal_error")
        self.assertEqual(result["failure_layer"], "tool_invocation")
        self.assertEqual(result["failure_kind"], "internal_error")
        # At minimum, exit code is captured
        self.assertEqual(result["exit_code"], 3)


# ─── Sanitization and workspace helpers ───────────────────────────────────────

class TestSanitizeTargets(unittest.TestCase):
    def test_valid_node_ids_pass(self):
        targets = ["tests/test_foo.py::test_bar", "tests/test_baz.py"]
        self.assertEqual(_sanitize_targets(targets), targets)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            _sanitize_targets(["../evil/test.py::test_bad"])

    def test_shell_metacharacters_rejected(self):
        for bad in ["; rm -rf /", "| cat /etc/passwd", "tests/foo.py && echo bad"]:
            with self.assertRaises(ValueError):
                _sanitize_targets([bad])

    def test_empty_and_none_filtered(self):
        self.assertEqual(_sanitize_targets(None), [])
        self.assertEqual(_sanitize_targets([]), [])
        self.assertEqual(_sanitize_targets(["", "  "]), [])


class TestResolveTestScope(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_none_returns_none(self):
        workspace = Path(self._tmpdir)
        self.assertIsNone(_resolve_test_scope(workspace, None))

    def test_relative_path_resolved(self):
        workspace = Path(self._tmpdir)
        sub = Path(self._tmpdir) / "tests"
        sub.mkdir()
        result = _resolve_test_scope(workspace, "tests")
        # Compare resolved paths (handles /var vs /private/var on macOS)
        self.assertEqual(Path(result).resolve(), sub.resolve())

    def test_escape_raises(self):
        workspace = Path(self._tmpdir)
        with self.assertRaises(ValueError):
            _resolve_test_scope(workspace, "../../etc")


# ─── Integration tests using real pytest subprocesses ────────────────────────

class TestInvokePytestIntegration(unittest.TestCase):
    """
    These tests write real Python test files to temp dirs and invoke pytest
    via invoke_pytest(). They validate end-to-end result structure.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orbit_pytest_test_")

    def _write_test_file(self, name: str, content: str) -> Path:
        p = Path(self._tmpdir) / name
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_all_tests_pass(self):
        self._write_test_file("test_pass.py", """
            def test_one():
                assert 1 + 1 == 2

            def test_two():
                assert "hello".upper() == "HELLO"
        """)
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        self.assertTrue(result["success"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["failures_total"], 0)
        self.assertEqual(result["counts"]["passed"], 2)

    def test_one_test_fails(self):
        self._write_test_file("test_fail.py", """
            def test_passing():
                assert True

            def test_failing():
                assert 1 == 2, "expected failure"
        """)
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        self.assertFalse(result["success"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["failures_total"], 1)
        self.assertEqual(len(result["failures"]), 1)
        failure = result["failures"][0]
        self.assertIn("test_failing", failure["node_id"])
        self.assertTrue(failure["headline"])  # should have a reason
        self.assertTrue(failure["excerpt"])   # should have a traceback body

    def test_multiple_failures_structure(self):
        self._write_test_file("test_multi_fail.py", """
            def test_fail_a():
                assert "x" == "y"

            def test_fail_b():
                raise RuntimeError("something broke")

            def test_pass():
                assert True
        """)
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        self.assertFalse(result["success"])
        self.assertEqual(result["failures_total"], 2)
        node_ids = [f["node_id"] for f in result["failures"]]
        self.assertTrue(any("test_fail_a" in nid for nid in node_ids))
        self.assertTrue(any("test_fail_b" in nid for nid in node_ids))

    def test_path_scoped_invocation(self):
        """Only tests in the given path should run."""
        subdir = Path(self._tmpdir) / "subdir"
        subdir.mkdir()
        (subdir / "test_sub.py").write_text(textwrap.dedent("""
            def test_in_subdir():
                assert True
        """))
        (Path(self._tmpdir) / "test_root.py").write_text(textwrap.dedent("""
            def test_in_root():
                assert False, "should not run"
        """))
        result = invoke_pytest(
            workspace_root=Path(self._tmpdir),
            path="subdir",
        )
        # Only subdir tests ran; root test (which fails) did not run
        self.assertTrue(result["success"])
        self.assertEqual(result["counts"]["passed"], 1)

    def test_keyword_filter(self):
        """The keyword -k filter should scope which tests run."""
        self._write_test_file("test_keyword.py", """
            def test_foo_bar():
                assert True

            def test_baz_qux():
                assert False, "should be filtered out"
        """)
        result = invoke_pytest(
            workspace_root=Path(self._tmpdir),
            keyword="foo",
        )
        # Only test_foo_bar should run
        self.assertTrue(result["success"])
        self.assertEqual(result["counts"]["passed"], 1)

    def test_max_failures_respected(self):
        """--maxfail stops pytest after N failures."""
        self._write_test_file("test_maxfail.py", """
            def test_fail_1():
                assert False

            def test_fail_2():
                assert False

            def test_fail_3():
                assert False
        """)
        result = invoke_pytest(
            workspace_root=Path(self._tmpdir),
            max_failures=1,
        )
        self.assertFalse(result["success"])
        # With --maxfail=1, only 1 failure should be recorded
        self.assertLessEqual(result["failures_total"], 1)

    def test_no_tests_collected(self):
        """An empty test directory gives exit_code=5 (no tests collected)."""
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        # No tests collected — not a failure
        self.assertTrue(result["success"])
        self.assertEqual(result["exit_code"], 5)
        collected = result["counts"]["collected"]
        self.assertTrue(collected == 0 or collected is None)

    def test_timeout_enforced(self):
        """A very short timeout should return timed_out=True for a slow test."""
        self._write_test_file("test_slow.py", """
            import time
            def test_sleepy():
                time.sleep(30)
        """)
        start = time.monotonic()
        result = invoke_pytest(
            workspace_root=Path(self._tmpdir),
            timeout_seconds=2.0,
        )
        elapsed = time.monotonic() - start
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["success"])
        self.assertIn("failure_layer", result)
        self.assertEqual(result["failure_kind"], "timeout")
        # Should not have waited the full 30 seconds
        self.assertLess(elapsed, 20.0)

    def test_specific_target_node_id(self):
        """Specifying a target node ID runs only that test."""
        self._write_test_file("test_targets.py", """
            def test_selected():
                assert True

            def test_not_selected():
                assert False, "should not run"
        """)
        result = invoke_pytest(
            workspace_root=Path(self._tmpdir),
            targets=["test_targets.py::test_selected"],
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["counts"]["passed"], 1)

    def test_failure_excerpt_is_bounded(self):
        """Failure excerpts are capped at MAX_EXCERPT_CHARS."""
        # Build a test that produces a very long error message
        self._write_test_file("test_longfail.py", f"""
            def test_long_error():
                raise AssertionError("x" * {MAX_EXCERPT_CHARS + 5000})
        """)
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        self.assertFalse(result["success"])
        self.assertEqual(len(result["failures"]), 1)
        excerpt_len = len(result["failures"][0]["excerpt"])
        self.assertLessEqual(excerpt_len, MAX_EXCERPT_CHARS)

    def test_invocation_metadata_present(self):
        """Result must always include invocation metadata."""
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        self.assertIn("invocation", result)
        inv = result["invocation"]
        self.assertIn("cwd", inv)
        self.assertIn("workspace_root", inv)
        self.assertIn("timeout_seconds", inv)
        self.assertIn("selection_basis", inv)
        self.assertIn(inv["selection_basis"], {"workspace_default", "path", "targets"})
        self.assertIn("command", inv)

    def test_best_effort_on_collection_error(self):
        """
        If pytest encounters a collection error (e.g., syntax error in test file),
        the result must still have the correct shape. parse_confidence may be partial
        or minimal, but the result must never raise or omit required fields.
        """
        # Write a test file with a syntax error to trigger a collection error.
        self._write_test_file("test_broken_syntax.py", """
            def test_ok():
                assert True

            def broken_function(
                # intentional syntax error: missing closing paren
        """)
        result = invoke_pytest(workspace_root=Path(self._tmpdir))
        # Should not raise; should return a valid result shape
        required = {"result_kind", "diagnostic_kind", "outcome_kind", "failure_layer", "failure_kind",
                    "success", "exit_code", "timed_out", "failures", "failures_total",
                    "failures_truncated", "raw_output_excerpt", "raw_output_truncated",
                    "parse_confidence", "counts", "invocation"}
        for field in required:
            self.assertIn(field, result)
        # Collection error is not a success
        self.assertFalse(result["success"])
        self.assertEqual(result["outcome_kind"], "collection_error")
        self.assertEqual(result["failure_layer"], "test_collection")
        self.assertEqual(result["failure_kind"], "collection_error")


if __name__ == "__main__":
    unittest.main()
