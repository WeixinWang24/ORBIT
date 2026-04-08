from __future__ import annotations

import unittest

from orbit.runtime.diagnostics.text_utils import preferred_raw_output, truncate_text


class DiagnosticsTextUtilsTests(unittest.TestCase):
    def test_truncate_text_keeps_short_text(self):
        text, truncated = truncate_text("hello", 10)
        self.assertEqual(text, "hello")
        self.assertFalse(truncated)

    def test_truncate_text_truncates_long_text(self):
        text, truncated = truncate_text("abcdefghij", 5)
        self.assertEqual(text, "abcde")
        self.assertTrue(truncated)

    def test_preferred_raw_output_prefers_stdout(self):
        self.assertEqual(preferred_raw_output(stdout="hello", stderr="error"), "hello")

    def test_preferred_raw_output_falls_back_to_stderr(self):
        self.assertEqual(preferred_raw_output(stdout="   ", stderr="error"), "error")

    def test_preferred_raw_output_empty_when_both_empty(self):
        self.assertEqual(preferred_raw_output(stdout="", stderr=""), "")


if __name__ == "__main__":
    unittest.main()
