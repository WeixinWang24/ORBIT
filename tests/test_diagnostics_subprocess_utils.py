from __future__ import annotations

import sys
import unittest
from pathlib import Path

from orbit.runtime.diagnostics.subprocess_utils import run_bounded_subprocess


class DiagnosticsSubprocessUtilsTests(unittest.TestCase):
    def test_run_bounded_subprocess_success(self):
        result = run_bounded_subprocess(
            cmd=[sys.executable, "-c", "print('hello')"],
            cwd=Path.cwd(),
            timeout_seconds=5.0,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertIn("hello", result["stdout"])

    def test_run_bounded_subprocess_stderr_capture(self):
        result = run_bounded_subprocess(
            cmd=[sys.executable, "-c", "import sys; print('oops', file=sys.stderr)"],
            cwd=Path.cwd(),
            timeout_seconds=5.0,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertIn("oops", result["stderr"])

    def test_run_bounded_subprocess_timeout(self):
        result = run_bounded_subprocess(
            cmd=[sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=Path.cwd(),
            timeout_seconds=0.2,
        )
        self.assertIsNone(result["exit_code"])
        self.assertTrue(result["timed_out"])


if __name__ == "__main__":
    unittest.main()
