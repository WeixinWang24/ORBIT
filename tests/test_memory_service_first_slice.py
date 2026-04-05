from __future__ import annotations

from pathlib import Path

from orbit.models import ConversationMessage, MemoryScope, MessageRole
from orbit.runtime.execution.context_assembly import build_text_only_prompt_assembly_plan
from orbit.runtime.memory_service import MemoryService
from orbit.store.sqlite_store import SQLiteStore


def test_memory_service_captures_session_turn_summary(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store)

    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="remember I prefer concise answers", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="Got it. I will keep things concise.", turn_index=2)

    records = service.capture_turn_memory(
        session_id="session_1",
        run_id="run_1",
        user_message=user,
        assistant_message=assistant,
    )

    assert len(records) == 1
    persisted = store.list_memory_records(scope="session", session_id="session_1", limit=10)
    assert len(persisted) == 1
    assert persisted[0].scope == MemoryScope.SESSION
    assert "concise" in persisted[0].detail_text


def test_prompt_assembly_accepts_memory_fragments(tmp_path):
    store = SQLiteStore(Path(tmp_path) / "orbit.db")
    service = MemoryService(store=store)
    user = ConversationMessage(session_id="session_1", role=MessageRole.USER, content="what do you remember?", turn_index=1)
    assistant = ConversationMessage(session_id="session_1", role=MessageRole.ASSISTANT, content="I remember your preferences.", turn_index=2)
    service.capture_turn_memory(session_id="session_1", run_id="run_1", user_message=user, assistant_message=assistant)

    fragments = service.retrieve_memory_fragments(session_id="session_1", query_text="preferences", limit=5)
    plan = build_text_only_prompt_assembly_plan(
        backend_name="openai-codex",
        model="gpt-5.4",
        messages=[user, assistant],
        workspace_root=None,
        memory_fragments=fragments,
    )

    assert plan.auxiliary_context_fragments
    assert plan.auxiliary_context_fragments[0].metadata["retrieval_mode"] == "pre_embedding_first_slice"
