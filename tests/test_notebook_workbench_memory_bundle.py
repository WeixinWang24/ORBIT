from __future__ import annotations

from pathlib import Path

from orbit.models import ConversationMessage, MessageRole
from orbit.notebook import NotebookWorkbench, capture_memory_showcase_turns, create_memory_showcase_bundle


def test_notebook_workbench_exposes_memory_summary_bundle():
    bundle = create_memory_showcase_bundle(db_path=Path('/tmp/orbit_memory_workbench_bundle.db'))
    store = bundle['store']
    session = bundle['session']
    service = bundle['service']

    workbench = NotebookWorkbench.from_store(store)

    capture_memory_showcase_turns(store=store, service=service, session=session)
    query_text = 'what are my concise orbit memory decisions and todos?'
    frames = workbench.memory_summary_frames(
        session_id=session.session_id,
        query_text=query_text,
    )
    status_df = workbench.memory_status_summary_frame(
        session_id=session.session_id,
        query_text=query_text,
    )

    assert frames['summary']['record_count'] >= 1
    assert frames['summary']['probe_artifact_count'] >= 1
    assert frames['summary']['has_embeddings'] is True
    assert frames['summary']['status']['postgres_mode'] == 'stub_compare_only'
    assert not frames['records'].empty
    assert not frames['scope_summary'].empty
    assert not frames['embeddings'].empty
    assert not frames['probe'].empty
    assert not frames['compare'].empty
    assert not frames['artifacts'].empty
    assert not status_df.empty
    assert 'retrieval_readiness' in status_df.columns
