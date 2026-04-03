from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.models import MessageRole
from orbit.runtime import DummyExecutionBackend, RuntimeEventType, SessionManager
from orbit.web_inspector import _html_page
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

    def __init__(self, path: str = "notes/contract-test.txt"):
        self.path = path

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
                tool_name="native__write_file",
                input_payload={
                    "path": self.path,
                    "content": "created by contract test\n",
                },
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
        )


class ApprovalReplaceThenFinishBackend:
    backend_name = "approval-replace-then-finish"

    def __init__(self, path: str = "notes/replace-target.txt"):
        self.path = path

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="Replace path completed and finalized.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="approval-needed",
            tool_request=ToolRequest(
                tool_name="native__replace_in_file",
                input_payload={
                    "path": self.path,
                    "old_text": "seed",
                    "new_text": "replaced",
                },
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
        )


class ApprovalReplaceAllThenFinishBackend:
    backend_name = "approval-replace-all-then-finish"

    def __init__(self, path: str = "notes/replace-all-target.txt", old_text: str = "seed", new_text: str = "replaced"):
        self.path = path
        self.old_text = old_text
        self.new_text = new_text

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="Replace-all path completed and finalized.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="approval-needed",
            tool_request=ToolRequest(
                tool_name="native__replace_all_in_file",
                input_payload={
                    "path": self.path,
                    "old_text": self.old_text,
                    "new_text": self.new_text,
                },
                requires_approval=True,
                side_effect_class="write",
            ),
            should_finish_after_tool=False,
        )


class ApprovalReplaceBlockThenFinishBackend:
    backend_name = "approval-replace-block-then-finish"

    def __init__(self, path: str = "notes/replace-block-target.txt", old_block: str = "alpha\nbeta\n", new_block: str = "alpha\nBETA\n"):
        self.path = path
        self.old_block = old_block
        self.new_block = new_block

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="Replace-block path completed and finalized.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="approval-needed",
            tool_request=ToolRequest(
                tool_name="native__replace_block_in_file",
                input_payload={
                    "path": self.path,
                    "old_block": self.old_block,
                    "new_block": self.new_block,
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
                tool_name="native__write_file",
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
                tool_name="native__read_file",
                input_payload={"path": "notes/existing.txt"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpReadThenFinishBackend:
    backend_name = "mcp-read-then-finish"

    def __init__(self, path: str = "notes/mcp-existing.txt", repeat_once: bool = False):
        self.path = path
        self.repeat_once = repeat_once

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if self.repeat_once and len(tool_results) == 1:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="mcp-safe-tool-repeat-needed",
                tool_request=ToolRequest(
                    tool_name="read_file",
                    input_payload={"path": self.path},
                    requires_approval=False,
                    side_effect_class="safe",
                ),
                should_finish_after_tool=True,
            )
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP safe read path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-safe-tool-needed",
            tool_request=ToolRequest(
                tool_name="read_file",
                input_payload={"path": self.path},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpPathEscapeBackend:
    backend_name = "mcp-path-escape"

    def plan_from_messages(self, messages, session=None):
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-path-escape-needed",
            tool_request=ToolRequest(
                tool_name="read_file",
                input_payload={"path": "../outside.txt"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpListDirectoryThenFinishBackend:
    backend_name = "mcp-list-directory-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP directory listing path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-list-directory-needed",
            tool_request=ToolRequest(
                tool_name="list_directory",
                input_payload={"path": "notes/listing"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpListDirectoryWithSizesThenFinishBackend:
    backend_name = "mcp-list-directory-with-sizes-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP directory listing with sizes path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-list-directory-with-sizes-needed",
            tool_request=ToolRequest(
                tool_name="list_directory_with_sizes",
                input_payload={"path": "notes/listing", "sortBy": "size"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpGetFileInfoThenFinishBackend:
    backend_name = "mcp-get-file-info-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP file info path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-get-file-info-needed",
            tool_request=ToolRequest(
                tool_name="get_file_info",
                input_payload={"path": "notes/info-target.txt"},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpDirectoryTreeThenFinishBackend:
    backend_name = "mcp-directory-tree-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP directory tree path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-directory-tree-needed",
            tool_request=ToolRequest(
                tool_name="directory_tree",
                input_payload={"path": "notes/tree-root", "maxDepth": 2},
                requires_approval=False,
                side_effect_class="safe",
            ),
            should_finish_after_tool=True,
        )


class McpSearchFilesThenFinishBackend:
    backend_name = "mcp-search-files-then-finish"

    def plan_from_messages(self, messages, session=None):
        tool_results = [m for m in messages if m.role == MessageRole.TOOL]
        if tool_results:
            return ExecutionPlan(
                source_backend=self.backend_name,
                plan_label="post-tool-final",
                final_text="MCP search files path completed in the same turn.",
            )
        return ExecutionPlan(
            source_backend=self.backend_name,
            plan_label="mcp-search-files-needed",
            tool_request=ToolRequest(
                tool_name="search_files",
                input_payload={"path": "notes/search-root", "query": "TODO", "maxResults": 10},
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
    def make_session_manager(self, backend, *, enable_mcp_filesystem: bool = False, workspace_root: Path | None = None) -> SessionManager:
        root = Path(tempfile.mkdtemp(prefix="orbit-mvp-loop-"))
        store = SQLiteStore(root / "orbit.db")
        resolved_workspace = workspace_root or root
        return SessionManager(
            store=store,
            backend=backend,
            workspace_root=str(resolved_workspace),
            enable_mcp_filesystem=enable_mcp_filesystem,
        )

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

    def test_mcp_non_approval_tool_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "mcp-existing.txt").write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        refreshed = sm.get_session(session.session_id)
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP safe read path completed in the same turn.")
        self.assertIsNone(sm.get_session(session.session_id).metadata.get("pending_approval"))
        self.assertIsNotNone(refreshed)
        self.assertIsNotNone(refreshed.governed_tool_state)
        self.assertEqual(refreshed.governed_tool_state.state, "executed")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "read_file")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        self.assertEqual(messages[-1].content, "MCP safe read path completed in the same turn.")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [
                RuntimeEventType.RUN_STARTED.value,
                RuntimeEventType.TOOL_INVOCATION_COMPLETED.value,
            ],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "read_file")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")
        read_state = refreshed.metadata.get("filesystem_read_state", {})
        self.assertIn("notes/mcp-existing.txt", read_state)
        self.assertFalse(read_state["notes/mcp-existing.txt"].get("is_partial_view"))
        self.assertEqual(read_state["notes/mcp-existing.txt"].get("grounding_kind"), "full_read")
        self.assertEqual(read_state["notes/mcp-existing.txt"].get("path_kind"), "file")

    def test_mcp_read_file_records_partial_view_when_truncated(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        long_content = "x" * (70 * 1024)
        (notes_dir / "truncated.txt").write_text(long_content, encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(path="notes/truncated.txt"),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")

        refreshed = sm.get_session(session.session_id)
        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertIsNotNone(refreshed)
        read_state = refreshed.metadata.get("filesystem_read_state", {})
        self.assertIn("notes/truncated.txt", read_state)
        self.assertTrue(read_state["notes/truncated.txt"].get("is_partial_view"))
        self.assertEqual(read_state["notes/truncated.txt"].get("grounding_kind"), "partial_read")
        self.assertEqual(read_state["notes/truncated.txt"].get("path_kind"), "file")

    def test_mcp_repeated_full_read_returns_explicit_unchanged_result(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "mcp-existing.txt").write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(repeat_once=True),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read twice via mcp")

        messages = sm.list_messages(session.session_id)
        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.TOOL, MessageRole.ASSISTANT])
        second_tool = messages[2]
        self.assertEqual(second_tool.metadata.get("message_kind"), "tool_result")
        self.assertEqual(second_tool.metadata.get("tool_name"), "read_file")
        structured = second_tool.metadata.get("tool_data", {}).get("raw_result", {}).get("structuredContent", {})
        self.assertEqual(second_tool.metadata.get("tool_data", {}).get("result_kind"), "filesystem_unchanged")
        self.assertEqual(structured.get("path"), "notes/mcp-existing.txt")
        self.assertEqual(structured.get("status"), "unchanged")
        self.assertEqual(structured.get("grounding_kind"), "full_read")
        freshness_basis = structured.get("freshness_basis", {})
        self.assertIsInstance(freshness_basis.get("modified_at_epoch"), (int, float))
        self.assertEqual(freshness_basis.get("size_bytes"), len("hello from mcp contract path\n".encode("utf-8")))

    def test_mcp_repeated_partial_read_does_not_return_unchanged_result(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        long_content = "x" * (70 * 1024)
        (notes_dir / "truncated.txt").write_text(long_content, encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(path="notes/truncated.txt", repeat_once=True),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read twice via mcp")

        messages = sm.list_messages(session.session_id)
        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.TOOL, MessageRole.ASSISTANT])
        second_tool = messages[2]
        structured = second_tool.metadata.get("tool_data", {}).get("raw_result", {}).get("structuredContent", {})
        self.assertNotEqual(second_tool.metadata.get("tool_data", {}).get("result_kind"), "filesystem_unchanged")
        self.assertEqual(structured.get("path"), "notes/truncated.txt")
        self.assertTrue(structured.get("truncated"))

    def test_mcp_repeated_full_read_does_not_return_unchanged_after_file_change(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "mcp-existing.txt"
        target.write_text("hello from mcp contract path\n", encoding="utf-8")

        class McpReadThenMutateThenRepeatBackend:
            backend_name = "mcp-read-then-mutate-then-repeat"

            def __init__(self, target_path: Path):
                self.target_path = target_path

            def plan_from_messages(self, messages, session=None):
                tool_results = [m for m in messages if m.role == MessageRole.TOOL]
                if len(tool_results) == 1:
                    self.target_path.write_text("changed after first read\nwith more bytes\n", encoding="utf-8")
                    return ExecutionPlan(
                        source_backend=self.backend_name,
                        plan_label="mcp-safe-tool-repeat-needed",
                        tool_request=ToolRequest(
                            tool_name="read_file",
                            input_payload={"path": "notes/mcp-existing.txt"},
                            requires_approval=False,
                            side_effect_class="safe",
                        ),
                        should_finish_after_tool=True,
                    )
                if tool_results:
                    return ExecutionPlan(
                        source_backend=self.backend_name,
                        plan_label="post-tool-final",
                        final_text="MCP safe read path completed in the same turn.",
                    )
                return ExecutionPlan(
                    source_backend=self.backend_name,
                    plan_label="mcp-safe-tool-needed",
                    tool_request=ToolRequest(
                        tool_name="read_file",
                        input_payload={"path": "notes/mcp-existing.txt"},
                        requires_approval=False,
                        side_effect_class="safe",
                    ),
                    should_finish_after_tool=True,
                )

        sm = self.make_session_manager(
            McpReadThenMutateThenRepeatBackend(target),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-mutate-then-repeat", model="test-model")
        plan = sm.run_session_turn(session_id=session.session_id, user_input="please read twice via mcp")

        self.assertEqual(plan.plan_label, "post-tool-final")
        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(len(tool_messages), 2)
        second_tool = tool_messages[-1]
        structured = second_tool.metadata.get("tool_data", {}).get("raw_result", {}).get("structuredContent", {})
        self.assertNotEqual(second_tool.metadata.get("tool_data", {}).get("result_kind"), "filesystem_unchanged")
        self.assertEqual(structured.get("path"), "notes/mcp-existing.txt")
        self.assertEqual(structured.get("content"), "changed after first read\nwith more bytes\n")

    def test_filesystem_grounding_status_for_path_none_without_prior_read(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        sm = self.make_session_manager(FinalOnlyBackend(), workspace_root=workspace_root)
        session = sm.create_session(backend_name="final-only", model="test-model")

        status = sm.filesystem_grounding_status_for_path(session=session, path="notes/missing.txt")
        self.assertEqual(status.get("status"), "none")
        self.assertFalse(status.get("fresh"))

    def test_filesystem_grounding_status_for_path_partial_only_after_truncated_read(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "truncated.txt").write_text("x" * (70 * 1024), encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(path="notes/truncated.txt"),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        status = sm.filesystem_grounding_status_for_path(session=refreshed, path="notes/truncated.txt")
        self.assertEqual(status.get("status"), "partial_only")
        self.assertEqual(status.get("grounding_kind"), "partial_read")
        self.assertFalse(status.get("fresh"))

    def test_filesystem_grounding_status_for_path_full_read_fresh_after_read(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "mcp-existing.txt").write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        status = sm.filesystem_grounding_status_for_path(session=refreshed, path="notes/mcp-existing.txt")
        self.assertEqual(status.get("status"), "full_read_fresh")
        self.assertEqual(status.get("grounding_kind"), "full_read")
        self.assertTrue(status.get("fresh"))

    def test_filesystem_grounding_status_for_path_full_read_stale_after_change(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "mcp-existing.txt"
        target.write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        target.write_text("changed after full read\n", encoding="utf-8")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        status = sm.filesystem_grounding_status_for_path(session=refreshed, path="notes/mcp-existing.txt")
        self.assertEqual(status.get("status"), "full_read_stale")
        self.assertEqual(status.get("grounding_kind"), "full_read")
        self.assertFalse(status.get("fresh"))

    def test_filesystem_write_readiness_for_path_none_without_prior_grounding(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        sm = self.make_session_manager(FinalOnlyBackend(), workspace_root=workspace_root)
        session = sm.create_session(backend_name="final-only", model="test-model")

        readiness = sm.filesystem_write_readiness_for_path(session=session, path="notes/missing.txt")
        self.assertFalse(readiness.get("eligible"))
        self.assertEqual(readiness.get("grounding_status"), "none")
        self.assertEqual(readiness.get("reason"), "no_prior_grounding")

    def test_filesystem_write_readiness_for_path_partial_read_is_ineligible(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "truncated.txt").write_text("x" * (70 * 1024), encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(path="notes/truncated.txt"),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        readiness = sm.filesystem_write_readiness_for_path(session=refreshed, path="notes/truncated.txt")
        self.assertFalse(readiness.get("eligible"))
        self.assertEqual(readiness.get("grounding_status"), "partial_only")
        self.assertEqual(readiness.get("reason"), "partial_read_grounding_insufficient")

    def test_filesystem_write_readiness_for_path_full_read_fresh_is_eligible(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "mcp-existing.txt").write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        readiness = sm.filesystem_write_readiness_for_path(session=refreshed, path="notes/mcp-existing.txt")
        self.assertTrue(readiness.get("eligible"))
        self.assertEqual(readiness.get("grounding_status"), "full_read_fresh")
        self.assertEqual(readiness.get("reason"), "full_read_fresh_grounding_available")

    def test_filesystem_write_readiness_for_path_full_read_stale_is_ineligible(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "mcp-existing.txt"
        target.write_text("hello from mcp contract path\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpReadThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        sm.run_session_turn(session_id=session.session_id, user_input="please read via mcp")
        target.write_text("changed after full read\n", encoding="utf-8")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)

        readiness = sm.filesystem_write_readiness_for_path(session=refreshed, path="notes/mcp-existing.txt")
        self.assertFalse(readiness.get("eligible"))
        self.assertEqual(readiness.get("grounding_status"), "full_read_stale")
        self.assertEqual(readiness.get("reason"), "stale_full_read_grounding")

    def test_native_write_is_blocked_without_prior_grounding_after_approval(self):
        sm = self.make_session_manager(ApprovalThenFinishBackend())
        session = sm.create_session(backend_name="approval-then-finish", model="test-model")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please write the file")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__write_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("failure_kind"), "grounding_readiness")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "no_prior_grounding")

    def test_native_write_is_blocked_with_stale_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-write-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "contract-test.txt"
        target.write_text("seed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/contract-test.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))
        target.write_text("changed after read\n", encoding="utf-8")

        sm = self.make_session_manager(ApprovalThenFinishBackend(path="notes/contract-test.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please write the file")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__write_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "stale_full_read_grounding")
        self.assertEqual(target.read_text(), "changed after read\n")

    def test_native_replace_is_blocked_without_prior_grounding_after_approval(self):
        sm = self.make_session_manager(ApprovalReplaceThenFinishBackend())
        session = sm.create_session(backend_name="approval-replace-then-finish", model="test-model")
        target = Path(sm.workspace_root) / "notes" / "replace-target.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("seed\n", encoding="utf-8")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace the text")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "no_prior_grounding")
        self.assertEqual(target.read_text(), "seed\n")

    def test_native_replace_is_blocked_with_stale_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-target.txt"
        target.write_text("seed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))
        target.write_text("seed changed\n", encoding="utf-8")

        sm = self.make_session_manager(ApprovalReplaceThenFinishBackend(path="notes/replace-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace the text")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "stale_full_read_grounding")
        self.assertEqual(target.read_text(), "seed changed\n")

    def test_native_replace_runs_with_fresh_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-target.txt"
        target.write_text("seed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceThenFinishBackend(path="notes/replace-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace the text")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_in_file")
        self.assertTrue(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("replacement_count"), 1)
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("before_excerpt"), "seed")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("after_excerpt"), "replaced")
        self.assertEqual(target.read_text(), "replaced\n")

    def test_native_replace_all_is_blocked_without_prior_grounding_after_approval(self):
        sm = self.make_session_manager(ApprovalReplaceAllThenFinishBackend())
        session = sm.create_session(backend_name="approval-replace-all-then-finish", model="test-model")
        target = Path(sm.workspace_root) / "notes" / "replace-all-target.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("seed\nseed\n", encoding="utf-8")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace all")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_all_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "no_prior_grounding")
        self.assertEqual(target.read_text(), "seed\nseed\n")

    def test_native_replace_all_is_blocked_with_stale_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-all-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-all-target.txt"
        target.write_text("seed\nseed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-all-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))
        target.write_text("seed changed\nseed changed\n", encoding="utf-8")

        sm = self.make_session_manager(ApprovalReplaceAllThenFinishBackend(path="notes/replace-all-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-all-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace all")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_all_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "stale_full_read_grounding")
        self.assertEqual(target.read_text(), "seed changed\nseed changed\n")

    def test_native_replace_all_runs_with_fresh_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-all-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-all-target.txt"
        target.write_text("seed\nseed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-all-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceAllThenFinishBackend(path="notes/replace-all-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-all-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace all")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_all_in_file")
        self.assertTrue(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("replacement_count"), 2)
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("before_excerpt"), "seed")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("after_excerpt"), "replaced")
        self.assertEqual(target.read_text(), "replaced\nreplaced\n")

    def test_native_replace_all_reports_tool_semantic_failure_when_old_text_missing(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-all-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-all-target.txt"
        target.write_text("seed\nseed\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-all-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceAllThenFinishBackend(path="notes/replace-all-target.txt", old_text="absent", new_text="replaced"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-all-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace all")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_all_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("failure_layer"), "tool_semantic")
        self.assertNotEqual(tool_messages[-1].metadata.get("tool_data", {}).get("failure_kind"), "grounding_readiness")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("replacement_count"), 0)
        self.assertEqual(target.read_text(), "seed\nseed\n")

    def test_native_replace_block_is_blocked_without_prior_grounding_after_approval(self):
        sm = self.make_session_manager(ApprovalReplaceBlockThenFinishBackend())
        session = sm.create_session(backend_name="approval-replace-block-then-finish", model="test-model")
        target = Path(sm.workspace_root) / "notes" / "replace-block-target.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace block")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_block_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "no_prior_grounding")
        self.assertEqual(target.read_text(), "alpha\nbeta\ngamma\n")

    def test_native_replace_block_is_blocked_with_stale_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-block-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-block-target.txt"
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-block-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))
        target.write_text("alpha\nbeta changed\ngamma\n", encoding="utf-8")

        sm = self.make_session_manager(ApprovalReplaceBlockThenFinishBackend(path="notes/replace-block-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-block-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace block")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_block_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("write_readiness", {}).get("reason"), "stale_full_read_grounding")
        self.assertEqual(target.read_text(), "alpha\nbeta changed\ngamma\n")

    def test_native_replace_block_runs_with_fresh_grounding_after_approval(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-block-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-block-target.txt"
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-block-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceBlockThenFinishBackend(path="notes/replace-block-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-block-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace block")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_block_in_file")
        self.assertTrue(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("match_count"), 1)
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("replacement_count"), 1)
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("before_excerpt"), "alpha\nbeta\n")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("after_excerpt"), "alpha\nBETA\n")
        self.assertEqual(target.read_text(), "alpha\nBETA\ngamma\n")

    def test_native_replace_block_reports_tool_semantic_failure_when_old_block_missing(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-block-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-block-target.txt"
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-block-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceBlockThenFinishBackend(path="notes/replace-block-target.txt", old_block="missing\nblock\n", new_block="new\nblock\n"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-block-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace block")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_block_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("failure_layer"), "tool_semantic")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("match_count"), 0)
        self.assertEqual(target.read_text(), "alpha\nbeta\ngamma\n")

    def test_native_replace_block_reports_tool_semantic_failure_when_old_block_matches_multiple_regions(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-native-replace-block-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target = notes_dir / "replace-block-target.txt"
        target.write_text("alpha\nbeta\nalpha\nbeta\ngamma\n", encoding="utf-8")

        read_sm = self.make_session_manager(McpReadThenFinishBackend(path="notes/replace-block-target.txt"), enable_mcp_filesystem=True, workspace_root=workspace_root)
        read_session = read_sm.create_session(backend_name="mcp-read-then-finish", model="test-model")
        read_sm.run_session_turn(session_id=read_session.session_id, user_input="please read first")
        read_refreshed = read_sm.get_session(read_session.session_id)
        self.assertIsNotNone(read_refreshed)
        grounding_state = dict(read_refreshed.metadata.get("filesystem_read_state", {}))

        sm = self.make_session_manager(ApprovalReplaceBlockThenFinishBackend(path="notes/replace-block-target.txt"), workspace_root=workspace_root)
        session = sm.create_session(backend_name="approval-replace-block-then-finish", model="test-model")
        session.metadata["filesystem_read_state"] = grounding_state
        sm.store.save_session(session)

        waiting_plan = sm.run_session_turn(session_id=session.session_id, user_input="please replace block")
        approvals = sm.list_open_session_approvals()
        session_approval = next(item for item in approvals if item["session_id"] == session.session_id)
        final_plan = sm.resolve_session_approval(
            session_id=session.session_id,
            approval_request_id=session_approval["approval_request_id"],
            decision="approve",
        )

        messages = sm.list_messages(session.session_id)
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(waiting_plan.plan_label, "approval-needed-waiting-for-approval")
        self.assertEqual(final_plan.plan_label, "post-tool-final")
        self.assertEqual(tool_messages[-1].metadata.get("tool_name"), "native__replace_block_in_file")
        self.assertFalse(tool_messages[-1].metadata.get("tool_ok"))
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("failure_layer"), "tool_semantic")
        self.assertEqual(tool_messages[-1].metadata.get("tool_data", {}).get("match_count"), 2)
        self.assertEqual(target.read_text(), "alpha\nbeta\nalpha\nbeta\ngamma\n")

    def test_web_inspector_renders_mutation_summary_for_tool_results(self):
        tool_data = {
            "mutation_kind": "replace_block_in_file",
            "path": "/tmp/example.txt",
            "match_count": 1,
            "replacement_count": 1,
            "before_excerpt": "alpha\nbeta\n",
            "after_excerpt": "alpha\nBETA\n",
        }
        class Msg:
            role = MessageRole.TOOL
            content = ""
            metadata = {
                "message_kind": "tool_result",
                "tool_name": "native__replace_block_in_file",
                "tool_ok": True,
                "tool_data": tool_data,
            }
        html = _html_page(
            sessions=[],
            current_session=None,
            transcript=[Msg()],
            events=[],
            artifacts=[],
            metadata={},
            tool_calls=[{
                "tool_name": "native__replace_block_in_file",
                "status": "completed",
                "requires_approval": True,
                "side_effect_class": "write",
                "result_payload": {"data": tool_data},
            }],
            active_tab="tool_calls",
        )
        self.assertIn("replace_block_in_file", html)
        self.assertIn("replacement_count=1", html)
        self.assertIn("match_count=1", html)
        self.assertIn("<strong>before</strong>", html)
        self.assertIn("<strong>after</strong>", html)

    def test_mcp_path_escape_is_denied_before_tool_execution(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        sm = self.make_session_manager(
            McpPathEscapeBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-path-escape", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="try path escape via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "mcp-path-escape-needed-deny")
        self.assertEqual(plan.final_text, "Current environment conditions do not allow read_file.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "policy_decision")
        self.assertEqual(messages[1].metadata.get("tool_name"), "read_file")
        self.assertEqual(messages[1].metadata.get("outcome"), "deny")
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [
                RuntimeEventType.RUN_STARTED.value,
                RuntimeEventType.RUN_FAILED.value,
            ],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "read_file")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "failed")
        self.assertEqual(invocations[0].result_payload.get("data", {}).get("failure_kind"), "policy_decision")
        self.assertEqual(invocations[0].result_payload.get("data", {}).get("outcome"), "deny")

    def test_mcp_list_directory_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        listing_dir = workspace_root / "notes" / "listing"
        listing_dir.mkdir(parents=True, exist_ok=True)
        (listing_dir / "a.txt").write_text("a\n", encoding="utf-8")
        (listing_dir / "b.txt").write_text("b\n", encoding="utf-8")
        (listing_dir / "subdir").mkdir(exist_ok=True)

        sm = self.make_session_manager(
            McpListDirectoryThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-list-directory-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please list directory via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP directory listing path completed in the same turn.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "list_directory")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        raw = messages[1].metadata.get("tool_data", {}).get("raw_result", {})
        structured = raw.get("structuredContent", {})
        self.assertEqual(structured.get("path"), "notes/listing")
        entry_names = [entry.get("name") for entry in structured.get("entries", [])]
        self.assertIn("a.txt", entry_names)
        self.assertIn("b.txt", entry_names)
        self.assertIn("subdir", entry_names)
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.TOOL_INVOCATION_COMPLETED.value],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "list_directory")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")

    def test_mcp_list_directory_with_sizes_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        listing_dir = workspace_root / "notes" / "listing"
        listing_dir.mkdir(parents=True, exist_ok=True)
        (listing_dir / "small.txt").write_text("a\n", encoding="utf-8")
        (listing_dir / "large.txt").write_text("abcdef\n", encoding="utf-8")
        (listing_dir / "subdir").mkdir(exist_ok=True)

        sm = self.make_session_manager(
            McpListDirectoryWithSizesThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-list-directory-with-sizes-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please list directory with sizes via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP directory listing with sizes path completed in the same turn.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "list_directory_with_sizes")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        raw = messages[1].metadata.get("tool_data", {}).get("raw_result", {})
        structured = raw.get("structuredContent", {})
        self.assertEqual(structured.get("path"), "notes/listing")
        self.assertEqual(structured.get("sort_by"), "size")
        self.assertIn("summary", structured)
        self.assertEqual(structured.get("summary", {}).get("file_count"), 2)
        entry_names = [entry.get("name") for entry in structured.get("entries", [])]
        self.assertIn("small.txt", entry_names)
        self.assertIn("large.txt", entry_names)
        self.assertIn("subdir", entry_names)
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.TOOL_INVOCATION_COMPLETED.value],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "list_directory_with_sizes")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")

    def test_mcp_get_file_info_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        notes_dir = workspace_root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "info-target.txt").write_text("hello info\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpGetFileInfoThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-get-file-info-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please get file info via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP file info path completed in the same turn.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "get_file_info")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        raw = messages[1].metadata.get("tool_data", {}).get("raw_result", {})
        structured = raw.get("structuredContent", {})
        self.assertEqual(structured.get("path"), "notes/info-target.txt")
        self.assertEqual(structured.get("kind"), "file")
        self.assertIsInstance(structured.get("size_bytes"), int)
        self.assertIsNotNone(structured.get("permissions_octal"))
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.TOOL_INVOCATION_COMPLETED.value],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "get_file_info")
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)
        self.assertNotIn("notes/info-target.txt", refreshed.metadata.get("filesystem_read_state", {}))
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")

    def test_mcp_directory_tree_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        root_dir = workspace_root / "notes" / "tree-root"
        (root_dir / "subdir").mkdir(parents=True, exist_ok=True)
        (root_dir / "subdir" / "nested.txt").write_text("nested\n", encoding="utf-8")
        (root_dir / "top.txt").write_text("top\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpDirectoryTreeThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-directory-tree-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please get directory tree via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP directory tree path completed in the same turn.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "directory_tree")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        raw = messages[1].metadata.get("tool_data", {}).get("raw_result", {})
        structured = raw.get("structuredContent", {})
        self.assertEqual(structured.get("path"), "notes/tree-root")
        self.assertEqual(structured.get("max_depth"), 2)
        self.assertIn("tree", structured)
        top_names = [entry.get("name") for entry in structured.get("tree", [])]
        self.assertIn("subdir", top_names)
        self.assertIn("top.txt", top_names)
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.TOOL_INVOCATION_COMPLETED.value],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "directory_tree")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")

    def test_mcp_search_files_turn_is_closure_complete_inside_run_session_turn(self):
        workspace_root = Path(tempfile.mkdtemp(prefix="orbit-mcp-workspace-"))
        root_dir = workspace_root / "notes" / "search-root"
        root_dir.mkdir(parents=True, exist_ok=True)
        (root_dir / "a.txt").write_text("TODO: one\nhello\n", encoding="utf-8")
        (root_dir / "b.txt").write_text("nothing\nTODO: two\n", encoding="utf-8")
        (root_dir / "subdir").mkdir(exist_ok=True)
        (root_dir / "subdir" / "c.txt").write_text("TODO: three\n", encoding="utf-8")

        sm = self.make_session_manager(
            McpSearchFilesThenFinishBackend(),
            enable_mcp_filesystem=True,
            workspace_root=workspace_root,
        )
        session = sm.create_session(backend_name="mcp-search-files-then-finish", model="test-model")

        plan = sm.run_session_turn(session_id=session.session_id, user_input="please search files via mcp")
        messages = sm.list_messages(session.session_id)
        events = sm.store.list_events_for_run(session.conversation_id)
        invocations = sm.store.list_tool_invocations_for_run(session.conversation_id)

        self.assertEqual(plan.plan_label, "post-tool-final")
        self.assertEqual(plan.final_text, "MCP search files path completed in the same turn.")
        self.assertEqual([m.role for m in messages], [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT])
        self.assertEqual(messages[1].metadata.get("message_kind"), "tool_result")
        self.assertEqual(messages[1].metadata.get("tool_name"), "search_files")
        self.assertTrue(messages[1].metadata.get("tool_ok"))
        raw = messages[1].metadata.get("tool_data", {}).get("raw_result", {})
        structured = raw.get("structuredContent", {})
        self.assertEqual(structured.get("path"), "notes/search-root")
        self.assertEqual(structured.get("query"), "TODO")
        self.assertEqual(structured.get("match_count"), 3)
        match_paths = [entry.get("path") for entry in structured.get("matches", [])]
        self.assertIn("notes/search-root/a.txt", match_paths)
        self.assertIn("notes/search-root/b.txt", match_paths)
        self.assertIn("notes/search-root/subdir/c.txt", match_paths)
        refreshed = sm.get_session(session.session_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.metadata.get("filesystem_read_state", {}), {})
        self.assertEqual(
            [getattr(event.event_type, "value", str(event.event_type)) for event in events],
            [RuntimeEventType.RUN_STARTED.value, RuntimeEventType.TOOL_INVOCATION_COMPLETED.value],
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].tool_name, "search_files")
        self.assertEqual(getattr(invocations[0].status, "value", str(invocations[0].status)), "completed")

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
