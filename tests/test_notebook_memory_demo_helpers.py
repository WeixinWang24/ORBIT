from __future__ import annotations

from orbit.notebook import build_durable_bias_service, capture_memory_showcase_turns, create_memory_showcase_bundle, memory_showcase_summary_frames


def test_memory_showcase_bundle_and_summary_frames_work_together():
    bundle = create_memory_showcase_bundle()
    store = bundle["store"]
    service = bundle["service"]
    session = bundle["session"]

    captured = capture_memory_showcase_turns(store=store, service=service, session=session)
    assert captured

    frames = memory_showcase_summary_frames(
        store=store,
        service=service,
        session=session,
        query_text="what are my concise orbit memory decisions and todos?",
    )
    assert frames["summary"]["record_count"] >= 1
    assert "current_backend_posture" in frames["summary"]
    assert frames["summary"]["has_durable_memory"] is True
    assert frames["summary"]["retrieval_readiness"] == "ready"
    assert "status" in frames["summary"]
    assert not frames["records"].empty
    assert not frames["scope_summary"].empty
    assert not frames["embeddings"].empty
    assert not frames["probe"].empty
    assert not frames["compare"].empty
    assert not frames["artifacts"].empty

    durable_service = build_durable_bias_service(store=store)
    durable_frames = memory_showcase_summary_frames(
        store=store,
        service=durable_service,
        session=session,
        query_text="what are my concise orbit memory decisions and todos?",
    )
    assert not durable_frames["probe"].empty
