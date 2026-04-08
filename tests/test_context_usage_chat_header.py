"""Focused tests for context usage display in the chat-mode header.

Covers:
- _fmt_tokens compact number formatting
- _format_context_usage projection → compact string
- build_chat_header: usage line present in chat mode
- build_chat_header: safe fallback when no usage recorded
- Other modes are unaffected (usage line is chat-only via build_chat_header signature)
"""
from __future__ import annotations

import unittest

from orbit.interfaces.runtime_cli_render import (
    _fmt_tokens,
    _format_context_usage,
    build_chat_header,
)
from orbit.interfaces.runtime_cli_state import RuntimeCliState, CHAT_MODE


class FakeSession:
    session_id = "sess-test-001"
    backend_name = "openai-codex"
    model = "gpt-5.4"


# ---------------------------------------------------------------------------
# Compact number formatter
# ---------------------------------------------------------------------------

class TestFmtTokens(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_fmt_tokens(0), "0")

    def test_below_thousand(self):
        self.assertEqual(_fmt_tokens(999), "999")
        self.assertEqual(_fmt_tokens(1), "1")

    def test_thousands(self):
        self.assertEqual(_fmt_tokens(1000), "1.0k")
        self.assertEqual(_fmt_tokens(4200), "4.2k")
        self.assertEqual(_fmt_tokens(18400), "18.4k")
        self.assertEqual(_fmt_tokens(999999), "1000.0k")

    def test_millions(self):
        self.assertEqual(_fmt_tokens(1_000_000), "1.0m")
        self.assertEqual(_fmt_tokens(1_200_000), "1.2m")


# ---------------------------------------------------------------------------
# Context usage projection formatter
# ---------------------------------------------------------------------------

class TestFormatContextUsage(unittest.TestCase):
    def _proj(self, *, latest_in=0, latest_out=0, total_in=0, total_out=0, calls=0):
        if calls == 0:
            return {"latest_call": None, "totals": {"call_count": 0, "total_input_tokens": 0, "total_output_tokens": 0}}
        return {
            "latest_call": {"input_tokens": latest_in, "output_tokens": latest_out},
            "totals": {"call_count": calls, "total_input_tokens": total_in, "total_output_tokens": total_out},
        }

    def test_zero_calls_returns_fallback(self):
        self.assertEqual(_format_context_usage(self._proj()), "Ctx: n/a")

    def test_null_latest_call_zero_calls_returns_fallback(self):
        proj = {"latest_call": None, "totals": {"call_count": 0}}
        self.assertEqual(_format_context_usage(proj), "Ctx: n/a")

    def test_empty_projection_returns_fallback(self):
        self.assertEqual(_format_context_usage({}), "Ctx: n/a")

    def test_calls_counted_but_no_token_data_shows_calls_only(self):
        # Provider returned no usage (all zero tokens) — show call count, not n/a.
        proj = self._proj(calls=3)  # zero tokens, 3 calls
        s = _format_context_usage(proj)
        self.assertEqual(s, "Calls 3")
        self.assertNotIn("n/a", s)
        self.assertNotIn("Ctx", s)

    def test_compact_format_with_usage(self):
        proj = self._proj(latest_in=4200, latest_out=612, total_in=18400, total_out=2100, calls=5)
        s = _format_context_usage(proj)
        self.assertIn("Ctx 4.2k/612", s)
        self.assertIn("18.4k/2.1k", s)
        self.assertIn("Calls 5", s)
        self.assertIn("\u03a3", s)  # Σ

    def test_sub_thousand_values(self):
        proj = self._proj(latest_in=25, latest_out=8, total_in=75, total_out=24, calls=3)
        s = _format_context_usage(proj)
        self.assertIn("Ctx 25/8", s)
        self.assertIn("75/24", s)
        self.assertIn("Calls 3", s)

    def test_single_call(self):
        proj = self._proj(latest_in=100, latest_out=50, total_in=100, total_out=50, calls=1)
        s = _format_context_usage(proj)
        self.assertIn("Calls 1", s)


# ---------------------------------------------------------------------------
# build_chat_header integration
# ---------------------------------------------------------------------------

class TestBuildChatHeader(unittest.TestCase):
    def _state(self):
        return RuntimeCliState()

    def test_usage_line_present_when_projection_provided(self):
        proj = {
            "latest_call": {"input_tokens": 4200, "output_tokens": 612},
            "totals": {"call_count": 5, "total_input_tokens": 18400, "total_output_tokens": 2100},
        }
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection=proj)
        combined = "\n".join(lines)
        self.assertIn("Ctx 4.2k/612", combined)
        self.assertIn("Calls 5", combined)

    def test_no_usage_fallback_when_projection_is_none(self):
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection=None)
        combined = "\n".join(lines)
        self.assertIn("Ctx: n/a", combined)

    def test_no_usage_fallback_when_projection_is_empty(self):
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection={})
        combined = "\n".join(lines)
        self.assertIn("Ctx: n/a", combined)

    def test_no_usage_when_call_count_zero(self):
        proj = {"latest_call": None, "totals": {"call_count": 0}}
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection=proj)
        combined = "\n".join(lines)
        self.assertIn("Ctx: n/a", combined)

    def test_calls_counted_no_tokens_shows_calls_not_na(self):
        # Simulates Codex API (no token data): call_count > 0 but all tokens = 0.
        proj = {
            "latest_call": {"input_tokens": 0, "output_tokens": 0},
            "totals": {"call_count": 2, "total_input_tokens": 0, "total_output_tokens": 0},
        }
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection=proj)
        combined = "\n".join(lines)
        self.assertNotIn("n/a", combined)
        self.assertIn("Calls 2", combined)

    def test_session_info_still_present_with_usage(self):
        proj = {
            "latest_call": {"input_tokens": 10, "output_tokens": 5},
            "totals": {"call_count": 1, "total_input_tokens": 10, "total_output_tokens": 5},
        }
        lines = build_chat_header(self._state(), FakeSession(), 120, usage_projection=proj)
        combined = "\n".join(lines)
        self.assertIn("sess-test-001", combined)
        self.assertIn("openai-codex", combined)

    def test_busy_state_does_not_break_usage_line(self):
        import time
        state = RuntimeCliState()
        state.runtime_busy = True
        state._submit_thread_started_at = time.time()
        proj = {
            "latest_call": {"input_tokens": 10, "output_tokens": 5},
            "totals": {"call_count": 1, "total_input_tokens": 10, "total_output_tokens": 5},
        }
        lines = build_chat_header(state, FakeSession(), 120, usage_projection=proj)
        combined = "\n".join(lines)
        self.assertIn("runtime busy", combined)
        self.assertIn("Ctx 10/5", combined)

    def test_narrow_terminal_does_not_crash(self):
        proj = {
            "latest_call": {"input_tokens": 4200, "output_tokens": 612},
            "totals": {"call_count": 5, "total_input_tokens": 18400, "total_output_tokens": 2100},
        }
        # Should not raise even at very narrow width
        lines = build_chat_header(self._state(), FakeSession(), 20, usage_projection=proj)
        self.assertIsInstance(lines, list)
        self.assertTrue(len(lines) > 0)


if __name__ == "__main__":
    unittest.main()
