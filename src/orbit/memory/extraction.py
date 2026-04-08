"""Memory extraction policy helpers for ORBIT.

This module provides a bounded extraction-policy v2 layer that shapes durable
memory candidates from transcript turns without yet requiring an LLM-based
extractor. It is meant to be more intentional than raw trigger-word checks
while still remaining deterministic and inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

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


def _clean_summary_clause(value: str) -> str:
    value = value.strip(" -:;,.。！？，、\n\t")
    value = re.sub(r"^(decision|lesson|takeaway|remember|决定|结论|经验|教训|记得)\s*[:：]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(remember to|don't forget|记得|待办是|经验是|教训是|结论是)\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _best_clause_for_markers(text: str, markers: list[str]) -> str:
    clauses = [_clean_summary_clause(part) for part in re.split(r"[\n.!?;,，；。！？]+", text) if part.strip()]
    lowered_clauses = [clause.lower() for clause in clauses]
    for marker in markers:
        marker_lower = marker.lower()
        for clause, lowered in zip(clauses, lowered_clauses):
            if marker_lower in lowered:
                return clause
    return _clean_summary_clause(text)


def extract_durable_candidates(*, user_text: str, assistant_text: str) -> list[DurableMemoryCandidate]:
    """Extract bounded durable-memory candidates from a completed turn.

    Current policy v2 remains deterministic, but improves over pure keyword
    checks by preferring clause-level candidate shaping and source selection.
    """
    candidates: list[DurableMemoryCandidate] = []
    user_lower = user_text.lower().strip()
    assistant_lower = assistant_text.lower().strip()

    if user_text:
        preference_markers = ["i prefer", "prefer ", "i like", "please keep", "我喜欢", "我更喜欢", "我希望", "我倾向于"]
        if any(marker in user_lower for marker in preference_markers):
            clause = _best_clause_for_markers(user_text, preference_markers)
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.USER_PREFERENCE,
                    summary_text=clause,
                    detail_text=user_text.strip(),
                    tags=["user_preference", "policy_v2_1", "multilingual_v1"],
                    salience=0.82,
                    confidence=0.8,
                    strategy="policy_v2_1_preference_clause",
                )
            )
        todo_markers = ["remember to", "need to", "todo", "we need to", "don't forget", "记得", "待办", "之后要", "需要先", "先把"]
        if any(marker in user_lower for marker in todo_markers):
            clause = _best_clause_for_markers(user_text, todo_markers)
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.TODO,
                    summary_text=clause,
                    detail_text=user_text.strip(),
                    tags=["todo", "policy_v2_1", "multilingual_v1"],
                    salience=0.86,
                    confidence=0.76,
                    strategy="policy_v2_1_todo_clause",
                )
            )

    decision_source = assistant_text.strip() or user_text.strip()
    decision_lower = assistant_lower or user_lower
    if decision_source:
        decision_markers = ["decision:", "we will", "we decided", "decided", "the plan is", "决定：", "决定:", "结论是", "定下来", "以后按"]
        if any(marker in decision_lower for marker in decision_markers):
            clause = _best_clause_for_markers(decision_source, decision_markers)
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.DECISION,
                    summary_text=clause,
                    detail_text=decision_source,
                    tags=["decision", "policy_v2_1", "multilingual_v1"],
                    salience=0.9,
                    confidence=0.8,
                    strategy="policy_v2_1_decision_clause",
                )
            )
        lesson_markers = ["lesson", "rule of thumb", "remember:", "takeaway", "经验：", "经验:", "教训", "学到", "重要发现"]
        if any(marker in decision_lower for marker in lesson_markers):
            clause = _best_clause_for_markers(decision_source, lesson_markers)
            candidates.append(
                DurableMemoryCandidate(
                    memory_type=MemoryType.LESSON,
                    summary_text=clause,
                    detail_text=decision_source,
                    tags=["lesson", "policy_v2_1", "multilingual_v1"],
                    salience=0.78,
                    confidence=0.74,
                    strategy="policy_v2_1_lesson_clause",
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
