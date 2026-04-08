"""Focused tests for the context usage accounting first slice.

Covers:
- ExecutionPlan.metadata passthrough
- Codex usage propagation through normalize_events
- Context usage accounting models
- ContextAccountingService: normalize, record, cumulate, project
- SessionManager: usage recorded on turns, no-usage turns safe
- SessionManager: usage recorded on rejection-continuation and tool-closure replan paths
- RuntimeAdapter: get_context_usage_projection, get_workbench_status includes projections
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.execution.normalization import (
    ProviderNormalizedResult,
    normalized_result_to_execution_plan,
)
from orbit.runtime.operations.context_usage_service import ContextAccountingService
from orbit.runtime.operations.context_usage_models import (
    ContextUsageSnapshot,
    ModelCallUsage,
    SessionUsageTotals,
)
from orbit.runtime import SessionManager
from orbit.store.sqlite_store import SQLiteStore
from orbit.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Minimal backends for integration tests
# ---------------------------------------------------------------------------

class _UsagePlanBackend:
    backend_name = "test-usage"

    class config:
        model = "gpt-test"

    def plan_from_messages(self, messages, session=None, on_partial_text=None, on_stream_completed=None):
        return ExecutionPlan(
            source_backend="test-usage",
            plan_label="test-final",
            final_text="Done.",
            metadata={"usage": {"input_tokens": 25, "output_tokens": 8}, "model": "gpt-test"},
        )


class _NoUsagePlanBackend:
    backend_name = "test-no-usage"

    class config:
        model = "gpt-test"

    def plan_from_messages(self, messages, session=None, on_partial_text=None, on_stream_completed=None):
        return ExecutionPlan(
            source_backend="test-no-usage",
            plan_label="test-final",
            final_text="Done.",
        )


class _ChatCompletionsUsageBackend:
    """Backend returning prompt_tokens/completion_tokens style."""
    backend_name = "test-chat"

    class config:
        model = "llama-3"

    def plan_from_messages(self, messages, session=None, on_partial_text=None, on_stream_completed=None):
        return ExecutionPlan(
            source_backend="test-chat",
            plan_label="test-final",
            final_text="Done.",
            metadata={"usage": {"prompt_tokens": 100, "completion_tokens": 20}, "model": "llama-3"},
        )


class _ToolThenFinalBackend:
    """Backend that first requests a safe (non-approval) tool, then returns final text.

    Each plan call reports distinct usage so we can count recorded calls.
    """
    backend_name = "test-tool-then-final"

    class config:
        model = "gpt-test"

    def __init__(self):
        self._call_count = 0

    def plan_from_messages(self, messages, session=None, on_partial_text=None, on_stream_completed=None):
        from orbit.models import MessageRole
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        self._call_count += 1
        if tool_results:
            # Second call: after tool result — return final text
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="Tool done.",
                metadata={"usage": {"input_tokens": 30, "output_tokens": 12}, "model": "gpt-test"},
            )
        # First call: request a safe (non-approval) read tool
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="tool-request",
            tool_request=ToolRequest(
                tool_name="native__list_available_tools",
                input_payload={},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=False,
            metadata={"usage": {"input_tokens": 20, "output_tokens": 5}, "model": "gpt-test"},
        )


class _RejectionContinuationBackend:
    """Backend that first requests an approval-gated tool; after rejection returns final text."""
    backend_name = "test-rejection-continuation"

    class config:
        model = "gpt-test"

    def plan_from_messages(self, messages, session=None, on_partial_text=None, on_stream_completed=None):
        from orbit.models import MessageRole
        # After the rejection assistant message is present, return final text
        assistant_msgs = [m for m in messages if m.role == MessageRole.ASSISTANT]
        if len(assistant_msgs) >= 1:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-rejection-final",
                final_text="Understood, skipping that.",
                metadata={"usage": {"input_tokens": 18, "output_tokens": 6}, "model": "gpt-test"},
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="approval-request",
            tool_request=ToolRequest(
                tool_name="native__write_file",
                input_payload={"path": "test.txt", "content": "x"},
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
            metadata={"usage": {"input_tokens": 15, "output_tokens": 4}, "model": "gpt-test"},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(backend, tmp):
    store = SQLiteStore(db_path=Path(tmp) / "test.db")
    return SessionManager(
        store=store,
        backend=backend,
        workspace_root=tmp,
        tool_registry=ToolRegistry(Path(tmp)),
    )


# ---------------------------------------------------------------------------
# 1. ExecutionPlan.metadata field
# ---------------------------------------------------------------------------

class TestExecutionPlanMetadata(unittest.TestCase):
    def test_default_empty(self):
        plan = ExecutionPlan(source_backend="s", plan_label="l")
        self.assertEqual(plan.metadata, {})

    def test_carries_arbitrary_metadata(self):
        plan = ExecutionPlan(
            source_backend="s",
            plan_label="l",
            metadata={"usage": {"input_tokens": 10}, "model": "gpt-x"},
        )
        self.assertEqual(plan.metadata["usage"]["input_tokens"], 10)
        self.assertEqual(plan.metadata["model"], "gpt-x")

    def test_independent_instances_do_not_share_dict(self):
        a = ExecutionPlan(source_backend="s", plan_label="l")
        b = ExecutionPlan(source_backend="s", plan_label="l")
        a.metadata["x"] = 1
        self.assertNotIn("x", b.metadata)


# ---------------------------------------------------------------------------
# 2. Normalization metadata passthrough
# ---------------------------------------------------------------------------

class TestNormalizationMetadataPassthrough(unittest.TestCase):
    def test_metadata_survives_normalization(self):
        result = ProviderNormalizedResult(
            source_backend="test",
            plan_label="test-plan",
            final_text="hello",
            metadata={"usage": {"input_tokens": 42}, "model": "gpt-5", "response_id": "r1"},
        )
        plan = normalized_result_to_execution_plan(result)
        self.assertEqual(plan.metadata["usage"]["input_tokens"], 42)
        self.assertEqual(plan.metadata["model"], "gpt-5")
        self.assertEqual(plan.metadata["response_id"], "r1")

    def test_empty_metadata_yields_empty_dict(self):
        result = ProviderNormalizedResult(
            source_backend="test",
            plan_label="test-plan",
            final_text="hi",
        )
        plan = normalized_result_to_execution_plan(result)
        self.assertEqual(plan.metadata, {})


# ---------------------------------------------------------------------------
# 3. Codex normalize_events usage propagation
# ---------------------------------------------------------------------------

class TestCodexNormalizeEventsUsage(unittest.TestCase):
    def _make_backend(self):
        from orbit.runtime.providers.openai_codex import OpenAICodexExecutionBackend, OpenAICodexConfig
        return OpenAICodexExecutionBackend(
            config=OpenAICodexConfig(enable_tools=False),
            tool_registry=ToolRegistry(Path(".")),
        )

    def _make_event(self, payload):
        from orbit.runtime.transports.openai_codex_http import OpenAICodexSSEEvent
        return OpenAICodexSSEEvent(payload=payload, raw_line="")

    def test_final_text_path_propagates_usage(self):
        backend = self._make_backend()
        events = [
            self._make_event({"type": "response.output_text.delta", "delta": "hi"}),
            self._make_event({
                "type": "response.completed",
                "response": {
                    "id": "r1",
                    "status": "completed",
                    "model": "gpt-5",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "output": [],
                },
            }),
        ]
        plan = backend.normalize_events(events)
        self.assertEqual(plan.metadata["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(plan.metadata["model"], "gpt-5")
        self.assertEqual(plan.metadata["response_id"], "r1")

    def test_missing_usage_yields_none_in_metadata(self):
        backend = self._make_backend()
        events = [
            self._make_event({"type": "response.output_text.delta", "delta": "hi"}),
            self._make_event({
                "type": "response.completed",
                "response": {"id": "r2", "status": "completed", "output": []},
            }),
        ]
        plan = backend.normalize_events(events)
        self.assertIsNone(plan.metadata.get("usage"))
        self.assertIsNone(plan.metadata.get("model"))


# ---------------------------------------------------------------------------
# 4. Context accounting models
# ---------------------------------------------------------------------------

class TestContextModels(unittest.TestCase):
    def test_model_call_usage_defaults(self):
        u = ModelCallUsage()
        self.assertEqual(u.input_tokens, 0)
        self.assertEqual(u.output_tokens, 0)
        self.assertEqual(u.provider, "")

    def test_session_usage_totals_defaults(self):
        t = SessionUsageTotals()
        self.assertEqual(t.call_count, 0)
        self.assertEqual(t.total_input_tokens, 0)

    def test_context_usage_snapshot_round_trip(self):
        snap = ContextUsageSnapshot(
            latest_call=ModelCallUsage(input_tokens=10, output_tokens=5, provider="p", model="m"),
            totals=SessionUsageTotals(total_input_tokens=10, total_output_tokens=5, call_count=1),
        )
        data = snap.model_dump(mode="json")
        snap2 = ContextUsageSnapshot.model_validate(data)
        self.assertEqual(snap2.latest_call.input_tokens, 10)
        self.assertEqual(snap2.totals.call_count, 1)


# ---------------------------------------------------------------------------
# 5. ContextAccountingService
# ---------------------------------------------------------------------------

class TestContextAccountingService(unittest.TestCase):
    def setUp(self):
        self.svc = ContextAccountingService()

    def test_normalize_input_output_style(self):
        u = self.svc.normalize_provider_usage(
            usage={"input_tokens": 20, "output_tokens": 10},
            provider="openai-codex",
            model="gpt-5",
        )
        self.assertIsNotNone(u)
        self.assertEqual(u.input_tokens, 20)
        self.assertEqual(u.output_tokens, 10)
        self.assertEqual(u.provider, "openai-codex")

    def test_normalize_prompt_completion_style(self):
        u = self.svc.normalize_provider_usage(
            usage={"prompt_tokens": 15, "completion_tokens": 7},
            provider="vllm",
            model="llama",
        )
        self.assertIsNotNone(u)
        self.assertEqual(u.input_tokens, 15)
        self.assertEqual(u.output_tokens, 7)

    def test_normalize_none_usage_returns_none(self):
        self.assertIsNone(self.svc.normalize_provider_usage(usage=None))

    def test_normalize_empty_usage_returns_none(self):
        self.assertIsNone(self.svc.normalize_provider_usage(usage={}))

    def test_normalize_zero_tokens_is_valid_not_none(self):
        # Explicit zero values mean "we got a response with 0 tokens" — not absent.
        u = self.svc.normalize_provider_usage(usage={"input_tokens": 0, "output_tokens": 0})
        self.assertIsNotNone(u)
        self.assertEqual(u.input_tokens, 0)
        self.assertEqual(u.output_tokens, 0)

    def test_normalize_cache_only_usage_is_valid(self):
        # Cache-read with zero prompt/output should still produce a valid record.
        u = self.svc.normalize_provider_usage(
            usage={"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 500},
            provider="openai-codex",
            model="gpt-5",
        )
        self.assertIsNotNone(u)
        self.assertEqual(u.cache_read_input_tokens, 500)
        self.assertEqual(u.input_tokens, 0)

    def test_normalize_cache_creation_only_is_valid(self):
        u = self.svc.normalize_provider_usage(
            usage={"cache_creation_input_tokens": 200},
        )
        self.assertIsNotNone(u)
        self.assertEqual(u.cache_creation_input_tokens, 200)
        self.assertEqual(u.input_tokens, 0)

    def test_normalize_reasoning_only_usage_is_valid(self):
        u = self.svc.normalize_provider_usage(
            usage={"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 150},
        )
        self.assertIsNotNone(u)
        self.assertEqual(u.reasoning_tokens, 150)

    def test_normalize_unknown_fields_only_returns_none(self):
        # A dict with only unrecognised keys should return None.
        self.assertIsNone(self.svc.normalize_provider_usage(usage={"some_unknown_field": 99}))

    def test_record_single_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(db_path=Path(tmp) / "t.db")
            from orbit.models import ConversationSession
            session = ConversationSession(conversation_id="c1", backend_name="b", model="m", runtime_mode="dev")
            store.save_session(session)
            session = store.get_session(session.session_id)

            call = ModelCallUsage(input_tokens=10, output_tokens=5, provider="p", model="m")
            self.svc.record_observed_usage(session=session, call_usage=call, store=store)
            session = store.get_session(session.session_id)
            snap = self.svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 1)
            self.assertEqual(snap.totals.total_input_tokens, 10)
            self.assertEqual(snap.latest_call.output_tokens, 5)

    def test_cumulative_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(db_path=Path(tmp) / "t.db")
            from orbit.models import ConversationSession
            session = ConversationSession(conversation_id="c1", backend_name="b", model="m", runtime_mode="dev")
            store.save_session(session)
            session = store.get_session(session.session_id)

            for i in range(3):
                session = store.get_session(session.session_id)
                call = ModelCallUsage(input_tokens=10, output_tokens=5, provider="p", model="m")
                self.svc.record_observed_usage(session=session, call_usage=call, store=store)

            session = store.get_session(session.session_id)
            snap = self.svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 3)
            self.assertEqual(snap.totals.total_input_tokens, 30)
            self.assertEqual(snap.totals.total_output_tokens, 15)

    def test_empty_session_returns_default_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(db_path=Path(tmp) / "t.db")
            from orbit.models import ConversationSession
            session = ConversationSession(conversation_id="c1", backend_name="b", model="m", runtime_mode="dev")
            store.save_session(session)
            session = store.get_session(session.session_id)
            snap = self.svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 0)
            self.assertIsNone(snap.latest_call)

    def test_build_status_projection_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(db_path=Path(tmp) / "t.db")
            from orbit.models import ConversationSession
            session = ConversationSession(conversation_id="c1", backend_name="b", model="m", runtime_mode="dev")
            store.save_session(session)
            session = store.get_session(session.session_id)

            call = ModelCallUsage(input_tokens=7, output_tokens=3, provider="p", model="x")
            self.svc.record_observed_usage(session=session, call_usage=call, store=store)
            session = store.get_session(session.session_id)
            proj = self.svc.build_status_projection(session=session)
            self.assertIn("latest_call", proj)
            self.assertIn("totals", proj)
            self.assertEqual(proj["latest_call"]["input_tokens"], 7)
            self.assertEqual(proj["totals"]["call_count"], 1)


# ---------------------------------------------------------------------------
# 6. SessionManager usage recording on turns
# ---------------------------------------------------------------------------

class TestSessionManagerUsageRecording(unittest.TestCase):
    def test_usage_recorded_after_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_UsagePlanBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="gpt-test")
            mgr.run_session_turn(session_id=session.session_id, user_input="hello")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap = svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 1)
            self.assertEqual(snap.totals.total_input_tokens, 25)
            self.assertEqual(snap.latest_call.output_tokens, 8)

    def test_no_usage_turn_still_counts_call(self):
        # Provider returns no token data — call is still recorded with zero tokens.
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_NoUsagePlanBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="gpt-test")
            mgr.run_session_turn(session_id=session.session_id, user_input="hello")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap = svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 1)
            self.assertEqual(snap.totals.total_input_tokens, 0)
            self.assertIsNotNone(snap.latest_call)

    def test_prompt_tokens_style_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_ChatCompletionsUsageBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="llama-3")
            mgr.run_session_turn(session_id=session.session_id, user_input="hello")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap = svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.total_input_tokens, 100)
            self.assertEqual(snap.totals.total_output_tokens, 20)

    def test_multi_turn_cumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_UsagePlanBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="gpt-test")
            mgr.run_session_turn(session_id=session.session_id, user_input="hello")
            mgr.run_session_turn(session_id=session.session_id, user_input="world")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap = svc.get_usage_snapshot(session=session)
            self.assertEqual(snap.totals.call_count, 2)
            self.assertEqual(snap.totals.total_input_tokens, 50)


# ---------------------------------------------------------------------------
# 7. RuntimeAdapter usage projection
# ---------------------------------------------------------------------------

class TestRuntimeAdapterUsageProjection(unittest.TestCase):
    def _make_adapter(self, backend, tmp):
        from orbit.interfaces.runtime_adapter import SessionManagerRuntimeAdapter
        from orbit.runtime.governance.build_state_store import BuildStateStore
        store = SQLiteStore(db_path=Path(tmp) / "test.db")
        mgr = SessionManager(
            store=store,
            backend=backend,
            workspace_root=tmp,
            tool_registry=ToolRegistry(Path(tmp)),
        )
        return SessionManagerRuntimeAdapter(
            session_manager=mgr,
            build_state_store=BuildStateStore(),
        )

    def test_projection_for_session_with_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._make_adapter(_UsagePlanBackend(), tmp)
            s = adapter.create_session()
            adapter.send_user_message(s.session_id, "hi")
            proj = adapter.get_context_usage_projection(s.session_id)
            self.assertEqual(proj["totals"]["call_count"], 1)
            self.assertEqual(proj["latest_call"]["input_tokens"], 25)

    def test_projection_for_unknown_session_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._make_adapter(_NoUsagePlanBackend(), tmp)
            proj = adapter.get_context_usage_projection("nonexistent-session")
            self.assertIsNone(proj["latest_call"])
            self.assertEqual(proj["totals"]["call_count"], 0)

    def test_workbench_status_includes_usage_projections(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._make_adapter(_UsagePlanBackend(), tmp)
            s = adapter.create_session()
            adapter.send_user_message(s.session_id, "hi")
            status = adapter.get_workbench_status()
            self.assertIn("session_usage_projections", status)
            self.assertIn(s.session_id, status["session_usage_projections"])
            self.assertEqual(
                status["session_usage_projections"][s.session_id]["totals"]["call_count"],
                1,
            )

    def test_workbench_status_no_usage_session_counts_call(self):
        # No token data from provider — call_count is still 1 after one turn.
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._make_adapter(_NoUsagePlanBackend(), tmp)
            s = adapter.create_session()
            adapter.send_user_message(s.session_id, "hi")
            status = adapter.get_workbench_status()
            proj = status["session_usage_projections"][s.session_id]
            self.assertEqual(proj["totals"]["call_count"], 1)
            self.assertEqual(proj["totals"]["total_input_tokens"], 0)


# ---------------------------------------------------------------------------
# 8. Usage recorded on all planning paths (Issue 2 fix coverage)
# ---------------------------------------------------------------------------

class TestUsageRecordedOnAllPlanningPaths(unittest.TestCase):
    """Verify usage is recorded on the non-approval tool-closure replan path
    and the rejection-continuation replan path, not only on the main turn path.
    """

    def test_tool_closure_replan_records_usage(self):
        """Non-approval tool turn: both the initial plan and the post-tool replan
        should each contribute one usage record (2 total call_count).
        """
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_ToolThenFinalBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="gpt-test")
            mgr.run_session_turn(session_id=session.session_id, user_input="read a file")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap = svc.get_usage_snapshot(session=session)
            # First plan (tool request) + second plan (post-tool final) = 2 calls
            self.assertEqual(snap.totals.call_count, 2)
            self.assertEqual(snap.totals.total_input_tokens, 50)   # 20 + 30
            self.assertEqual(snap.totals.total_output_tokens, 17)  # 5 + 12

    def test_rejection_continuation_replan_records_usage(self):
        """Approval-gated tool rejected: the initial plan AND the continuation
        replan should both contribute usage records (2 total call_count).
        """
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _make_manager(_RejectionContinuationBackend(), tmp)
            session = mgr.create_session(backend_name="test", model="gpt-test")
            # First turn: backend returns approval request (usage recorded), then
            # session waits for approval.
            mgr.run_session_turn(session_id=session.session_id, user_input="write a file")
            session = mgr.get_session(session.session_id)
            svc = ContextAccountingService()
            snap_after_request = svc.get_usage_snapshot(session=session)
            self.assertEqual(snap_after_request.totals.call_count, 1)

            # Reject the approval — triggers continuation replan (second provider call).
            pending = session.metadata.get("pending_approval", {})
            approval_request_id = pending.get("approval_request_id")
            mgr.resolve_session_approval(
                session_id=session.session_id,
                approval_request_id=approval_request_id,
                decision="reject",
            )
            session = mgr.get_session(session.session_id)
            snap_after_reject = svc.get_usage_snapshot(session=session)
            # Initial plan + continuation replan = 2
            self.assertEqual(snap_after_reject.totals.call_count, 2)
            self.assertEqual(snap_after_reject.totals.total_input_tokens, 33)   # 15 + 18
            self.assertEqual(snap_after_reject.totals.total_output_tokens, 10)  # 4 + 6


if __name__ == "__main__":
    unittest.main()
