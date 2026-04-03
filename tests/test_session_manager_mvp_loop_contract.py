from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.models import MessageRole
from orbit.runtime import DummyExecutionBackend, RuntimeEventType, SessionManager
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStoreError
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.store.sqlite_store import SQLiteStore


class FinalOnlyBackend:
    backend_name = "final-only"

    def plan_from_messages(self, messages, session=None):
        if session is not None:
            session.metadata["_pending_context_assembly"] = {
                "backend": "final-only",
                "instructions": "final-only test instructions",
                "projected_input": [
                    {"role": getattr(m.role, "value", str(m.role)), "content": m.content}
                    for m in messages
                ],
            }
            session.metadata["_pending_provider_payload"] = {
                "backend": "final-only",
                "messages": [
                    {"role": getattr(m.role, "value", str(m.role)), "content": m.content}
                    for m in messages
                ],
            }
        return ExecutionPlan(
            source_backend="final-only",
            plan_label="final-only",
            final_text="Final answer without tool use.",
        )


class ApprovalThenFinishBackend:
    backend_name = "approval-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend="approval-then-finish",
                plan_label="post-tool-final",
                final_text="Tool path completed and finalized.",
            )
        return ExecutionPlan(
            source_backend="approval-then-finish",
            plan_label="approval-needed",
            tool_request=ToolRequest(
                tool_name="write_file",
                input_payload={
                    "path": "notes/contract-test.txt",
                    "content": "created by contract test\n",
                },
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
        )


class ApprovalRejectContinuationBackend:
    backend_name = "approval-reject-continuation"

    def plan_from_messages(self, messages, session=None):
        assistant_kinds = [m.metadata.get("message_kind") for m in messages if m.role == MessageRole.ASSISTANT]
        if "approval_decision" in assistant_kinds:
            return ExecutionPlan(
                source_backend="approval-reject-continuation",
                plan_label="post-rejection-final",
                final_text="Understood — I will continue without executing that tool.",
            )
        return ExecutionPlan(
            source_backend="approval-reject-continuation",
            plan_label="approval-needed",
            tool_request=ToolRequest(
                tool_name="write_file",
                input_payload={
                    "path": "notes/reject-contract-test.txt",
                    "content": "should not be written\n",
                },
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
        )


class NonApprovalToolThenFinishBackend:
    backend_name = "non-approval-tool-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend="non-approval-tool-then-finish",
                plan_label="post-tool-final",
                final_text="Safe tool path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend="non-approval-tool-then-finish",
            plan_label="safe-tool-needed",
            tool_request=ToolRequest(
                tool_name="read_file",
                input_payload={"path": "notes/existing.txt"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class ProviderFailureBackend:
    backend_name = "provider-failure"

    def plan_from_messages(self, messages, session=None):
        return ExecutionPlan(
            source_backend="provider-failure",
            plan_label="provider-failure",
            failure_reason="Upstream provider transport failed.",
        )


class MalformedResponseBackend:
    backend_name = "malformed-response"

    def plan_from_messages(self, messages, session=None):
        return ExecutionPlan(
            source_backend="malformed-response",
            plan_label="malformed-response",
            failure_reason="Provider response did not contain extractable final text.",
        )


class AuthFailureBackend:
    backend_name = "auth-failure"

    def plan_from_messages(self, messages, session=None):
        raise OpenAIAuthStoreError("OpenAI auth store not found for contract test")


class SessionManagerMvpLoopContractTests(unittest.TestCase):
    def make_session_manager(self, backend) -> SessionManager:
        root = Path(tempfile.mkdtemp(prefix="orbit-mvp-loop-"))
        store = SQLiteStore(root / "orbit.db")
        return SessionManager(store=store, backend=backend, workspace_root=str(root))

    def test_plain_text_turn_is_closure_complete(self):
        sm = self.make_session_manager(FinalOnlyBackend())
        session = sm.create_session(backend_name="final-only", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="hello")
        messages = sm.list_messages(session.session_id)
        artifacts = sm.store.list_context_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "final-only")
        self.assertIsNone(plan.tool_request)
        self.assertEqual(plan.final_text, "Final answer without tool use.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.ASSISTANT])
        self.assertEqual(messages[-1].content, "Final answer without tool use.")
        artifact_types = [artifact.artifact_type for artifact in artifacts]
        self.assertIn("session_transcript_snapshot", artifact_types)
        self.assertIn("session_context_assembly", artifact_types)
        self.assertIn("session_provider_payload", artifact_types)
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)
        self.assertIn("last_context_assembly", refreshed.metadata)
        self.assertIn("last_provider_payload", refreshed.metadata)

    def test_approval_turn_persists_waiting_state_and_emits_event(self):
        sm = self.make_session_manager(ApprovalThenFinishBackend())
        session = sm.create_session(backend_name="approval-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please write the file")
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertIsNotNone(plan.tool_request)
        self.assertTrue(plan.tool_request.requires_approval)
        self.assertEqual(plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(messages[-1].metadata.get("message_kind"), "approval_request")
        self.assertIsNotNone(refreshed)
        self.assertIsNotNone(refreshed.governed_tool_state)
        self.assertEqual(refreshed.governed_tool_state.state, "waiting_for_approval")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.APPROVAL_REQUESTED.value],
        )

    def test_approval_resolution_resumes_to_bounded_completion(self):
        sm = self.make_session_manager(ApprovalThenFinishBackend())
        session = sm.create_session(backend_name="approval-then-finish", model="test-model")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please write the file")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)

        resumed_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
            note="approved by contract test",
        )
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(resumed_plan.plan_label, "post-tool-final")
        self.assertEqual(resumed_plan.final_text, "Tool path completed and finalized.")
        self.assertEqual(messages[-1].role, MessageRole.ASSISTANT)
        self.assertEqual(messages[-1].content, "Tool path completed and finalized.")
        self.assertIsNotNone(refreshed)
        self.assertIsNotNone(refreshed.governed_tool_state)
        self.assertEqual(refreshed.governed_tool_state.state, "executed")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [
                RuntimeEventType.RUN_STARTED.value,
                RuntimeEventType.APPROVAL_REQUESTED.value,
                RuntimeEventType.APPROVAL_GRANTED.value,
                RuntimeEventType.TOOL_INVOCATION_COMPLETED.value,
            ],
        )

    def test_approval_rejection_resumes_without_tool_execution(self):
        sm = self.make_session_manager(ApprovalRejectContinuationBackend())
        session = sm.create_session(backend_name="approval-reject-continuation", model="test-model")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please write the file")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)

        resumed_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="reject",
            note="rejected by contract test",
        )
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(resumed_plan.plan_label, "post-rejection-final")
        self.assertEqual(resumed_plan.final_text, "Understood — I will continue without executing that tool.")
        self.assertEqual(messages[-1].role, MessageRole.ASSISTANT)
        self.assertEqual(messages[-1].content, "Understood — I will continue without executing that tool.")
        self.assertEqual(messages[-1].metadata.get("continued_after_tool_rejection"), True)
        self.assertIsNotNone(refreshed)
        self.assertIsNotNone(refreshed.governed_tool_state)
        self.assertEqual(refreshed.governed_tool_state.state, "rejected")
        self.assertFalse(any(m.role == MessageRole.TOOL for m in messages))
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [
                RuntimeEventType.RUN_STARTED.value,
                RuntimeEventType.APPROVAL_REQUESTED.value,
                RuntimeEventType.APPROVAL_REJECTED.value,
            ],
        )

    def test_non_approval_tool_turn_is_closure_complete_inside_run_session_turn(self):
        sm = self.make_session_manager(NonApprovalToolThenFinishBackend())
        workspace_root = Path(sm.workspace_root)
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "existing.txt").write_text("hello from safe tool path\n", encoding="utf-8")
        session = sm.create_session(backend_name="non-approval-tool-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read the file")
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "Safe tool path completed in the same turn.")
        self.assertIsNone(sm.get_session(session.session_id).metadata.get("pending_approval"))
        self.assertIsNotNone(refreshed)
        self.assertIsNotNone(refreshed.governed_tool_state)
        self.assertEqual(refreshed.governed_tool_state.state, "executed")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[-1].content, "Safe tool path completed in the same turn.")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [
                RuntimeEventType.RUN_STARTED.value,
                RuntimeEventType.TOOL_INVOCATION_COMPLETED.value,
            ],
        )

    def test_provider_failure_turn_becomes_transcript_visible_runtime_failure(self):
        sm = self.make_session_manager(ProviderFailureBackend())
        session = sm.create_session(backend_name="provider-failure", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="hello")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "provider-failure")
        self.assertEqual(plan.failure_reason, "Upstream provider transport failed.")
        self.assertEqual(messages[-1].role, MessageRole.ASSISTANT)
        self.assertEqual(messages[-1].metadata.get("message_kind"), "runtime_failure")
        self.assertEqual(messages[-1].metadata.get("failure_reason"), "Upstream provider transport failed.")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.RUN_FAILED.value],
        )

    def test_malformed_response_turn_becomes_transcript_visible_runtime_failure(self):
        sm = self.make_session_manager(MalformedResponseBackend())
        session = sm.create_session(backend_name="malformed-response", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="hello")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "malformed-response")
        self.assertEqual(plan.failure_reason, "Provider response did not contain extractable final text.")
        self.assertEqual(messages[-1].role, MessageRole.ASSISTANT)
        self.assertEqual(messages[-1].metadata.get("message_kind"), "runtime_failure")
        self.assertEqual(messages[-1].metadata.get("failure_reason"), "Provider response did not contain extractable final text.")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.RUN_FAILED.value],
        )

    def test_auth_failure_becomes_session_readable_but_transcript_invisible(self):
        sm = self.make_session_manager(AuthFailureBackend())
        session = sm.create_session(backend_name="auth-failure", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="hello")
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        artifacts = sm.store.list_context_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "auth-failure")
        self.assertEqual(plan.failure_reason, "OpenAI auth store not found for contract test")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[-1].role, MessageRole.USER)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.metadata.get("last_auth_failure", {}).get("message"), "OpenAI auth store not found for contract test")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.RUN_FAILED.value],
        )
        self.assertEqual(artifacts[-1].artifact_type, "session_auth_failure")
        self.assertIn("OpenAI auth store not found for contract test", artifacts[-1].content)


if __name__ == "__main__":
    unittest.main()
