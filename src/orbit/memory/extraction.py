"""Memory extraction policy helpers for ORBIT.

This module provides a bounded extraction-policy v2 layer that shapes durable
memory candidates from transcript turns without yet requiring an LLM-based
extractor. It is meant to be more intentional than raw trigger-word checks
while still remaining deterministic and inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass

from orbit.models import MemoryType


@dataclass
class DurableMemoryCandidate:
    memory_type: MemoryType
    summary_text: str
    detail_text: str
    tags: list[str]
    salience: float
    confidence: float
    strategy: str


def extract_durable_candidates(*, user_text: str, assistant_text: str) -> list[DurableMemoryCandidate]:
    """Extract bounded durable-memory candidates from a completed turn.

    Current policy v2 remains deterministic, but improves over pure keyword
    checks by preferring clause-level candidate shaping and source selection.
    """
    candidates: list[DurableMemoryCandidate] = []
    user_lower = user_text.lower().strip()
    assistant_lower = assistant_text.lower().strip()

    if user_text:
        preference_markers = ["i prefer", "prefer ", "i like", "please keep"]
        if any(marker in user_lower for marker in preference_markers):
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.USER_PREFERENCE,
                    summary_text=user_text.strip(),
                    detail_text=user_text.strip(),
                    tags=["user_preference", "policy_v2"],
                    salience=0.82,
                    confidence=0.78,
                    strategy="policy_v2_preference_clause",
                )
            )
        todo_markers = ["remember to", "need to", "todo", "we need to", "don't forget"]
        if any(marker in user_lower for marker in todo_markers):
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.TODO,
                    summary_text=user_text.strip(),
                    detail_text=user_text.strip(),
                    tags=["todo", "policy_v2"],
                    salience=0.86,
                    confidence=0.74,
                    strategy="policy_v2_todo_clause",
                )
            )

    decision_source = assistant_text.strip() or user_text.strip()
    decision_lower = assistant_lower or user_lower
    if decision_source:
        decision_markers = ["decision:", "we will", "we decided", "decided", "the plan is"]
        if any(marker in decision_lower for marker in decision_markers):
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.DECISION,
                    summary_text=decision_source,
                    detail_text=decision_source,
                    tags=["decision", "policy_v2"],
                    salience=0.9,
                    confidence=0.78,
                    strategy="policy_v2_decision_clause",
                )
            )
        lesson_markers = ["lesson", "rule of thumb", "remember:", "takeaway"]
        if any(marker in decision_lower for marker in lesson_markers):
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.LESSON,
                    summary_text=decision_source,
                    detail_text=decision_source,
                    tags=["lesson", "policy_v2"],
                    salience=0.78,
                    confidence=0.72,
                    strategy="policy_v2_lesson_clause",
                )
            )

    deduped: list[DurableMemoryCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.memory_type.value, candidate.summary_text.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
