from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from orbit.interfaces.pty_debug import debug_log
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.execution.contracts.plans import ExecutionPlan


@dataclass
class PostTurnObservationResult:
    metadata: dict
    timings: dict[str, float]


class PostTurnObserver(Protocol):
    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        ...


class NoOpPostTurnObserver:
    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        return PostTurnObservationResult(metadata={}, timings={})


class DetachedKnowledgePostTurnObserver:

    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        assistant_message = next((message for message in reversed(messages) if message.role == MessageRole.ASSISTANT and message.content.strip()), None)
        if assistant_message is None:
            return PostTurnObservationResult(metadata={}, timings={"knowledge_post_turn_ms": 0.0})
        metadata = {
            "last_knowledge_post_turn": {
                "session_id": session.session_id,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "assistant_turn_index": assistant_message.turn_index,
                "assistant_message_kind": assistant_message.metadata.get("message_kind") if isinstance(assistant_message.metadata, dict) else None,
                "runtime_profile": runtime_profile,
            }
        }
        return PostTurnObservationResult(metadata=metadata, timings={"knowledge_post_turn_ms": 0.0})


class DetachedMemoryCaptureObserver:

    def __init__(self, *, memory_service=None):
        self.memory_service = memory_service

    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        if self.memory_service is None:
            return PostTurnObservationResult(metadata={}, timings={"memory_capture_ms": 0.0})

        started_at = time.perf_counter()
        assistant_message = next((message for message in reversed(messages) if message.role == MessageRole.ASSISTANT and message.content.strip()), None)
        user_message = None
        if assistant_message is not None:
            for message in reversed(messages):
                if message.created_at <= assistant_message.created_at and message.role == MessageRole.USER and message.content.strip():
                    user_message = message
                    break
        records = self.memory_service.capture_turn_memory(
            session_id=session.session_id,
            run_id=session.conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        try:
            debug_log(
                "post_turn_observer:memory_capture "
                + json.dumps(
                    {
                        "session_id": session.session_id,
                        "elapsed_ms": elapsed_ms,
                        "record_count": len(records) if records else 0,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
        metadata = {}
        if records:
            metadata["last_memory_capture"] = {
                "memory_ids": [record.memory_id for record in records],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "count": len(records),
            }
        return PostTurnObservationResult(metadata=metadata, timings={"memory_capture_ms": elapsed_ms})


class CompositePostTurnObserver:

    def __init__(self, *observers: PostTurnObserver):
        self.observers = [observer for observer in observers if observer is not None]

    def on_turn_completed(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        messages: list[ConversationMessage],
        runtime_profile: str,
    ) -> PostTurnObservationResult:
        metadata: dict = {}
        timings: dict[str, float] = {}
        for observer in self.observers:
            result = observer.on_turn_completed(
                session=session,
                plan=plan,
                messages=messages,
                runtime_profile=runtime_profile,
            )
            if isinstance(result.metadata, dict):
                metadata.update(result.metadata)
            if isinstance(result.timings, dict):
                timings.update(result.timings)
        return PostTurnObservationResult(metadata=metadata, timings=timings)
