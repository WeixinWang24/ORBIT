"""Continuation-context helpers for governed transcript replay.

This module exists to keep local continuation shaping explicit rather than
burying it inside session orchestration or provider projection incidentally.
The first use case is approval-rejection continuation after a tool request was
blocked by governance.
"""

from __future__ import annotations

from pydantic import Field

from orbit.models import ConversationMessage
from orbit.models.core import OrbitBaseModel


class ContinuationContextPackage(OrbitBaseModel):
    """Represent a bounded continuation-context package for the next provider call.

    This package is intentionally separate from canonical transcript truth.
    It describes local next-turn steering artifacts that may accompany a
    continuation request without pretending to be the transcript itself.
    """

    context_kind: str
    bridge_message: ConversationMessage | None = None
    system_prompt: str | None = None
    allowed_next_actions: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


DEFAULT_REJECTION_ALLOWED_NEXT_ACTIONS = [
    "Explain to the user why the requested tool was not executed.",
    "Choose a different safe tool only if it is genuinely helpful.",
    "Think through a different non-side-effecting solution.",
]



def build_rejection_continuation_bridge(messages: list[ConversationMessage]) -> ConversationMessage | None:
    """Return a local bridge message after a recent approval rejection.

    The goal is not to replace transcript truth. The goal is to create a small,
    explicit continuation handoff that re-weights the most important governed
    facts for the next provider call.
    """
    if not messages:
        return None
    last = messages[-1]
    kind = last.metadata.get("message_kind") if isinstance(last.metadata, dict) else None
    decision = last.metadata.get("decision") if isinstance(last.metadata, dict) else None
    if kind != "approval_decision" or decision != "rejected":
        return None

    tool_name = last.metadata.get("tool_name")
    note = last.metadata.get("note")
    note_suffix = f" Note: {note}" if note else ""
    return ConversationMessage(
        session_id=last.session_id,
        role=last.role,
        content=(
            f"Continuation bridge: the previously requested tool `{tool_name}` was rejected by governance and was not executed.{note_suffix} "
            "You must continue truthfully from that state. Do not claim that the tool ran or that its side effects occurred. "
            "Acknowledge the rejection and continue with a safe alternative, explanation, or next non-side-effecting step."
        ),
        turn_index=last.turn_index,
        metadata={
            "message_kind": "continuation_bridge",
            "bridge_kind": "approval_rejection",
            "tool_name": tool_name,
            "tool_executed": False,
            "source_message_kind": "approval_decision",
        },
    )



def build_next_allowed_actions_system_prompt(*, tool_name: str, note: str | None = None) -> str:
    """Return the current dummy governance steering prompt for rejection continuation."""
    note_suffix = f" Rejection note: {note}" if note else ""
    bullets = "\n".join(f"- {item}" for item in DEFAULT_REJECTION_ALLOWED_NEXT_ACTIONS)
    return (
        f"Governance constraint for this continuation: the previously requested tool {tool_name} was rejected and must not be called again in this turn.{note_suffix}\n"
        "Allowed next actions are only:\n"
        f"{bullets}\n"
        f"You must not call {tool_name} again unless the human explicitly re-authorizes it in a later turn."
    )



def build_rejection_continuation_context(messages: list[ConversationMessage]) -> ContinuationContextPackage | None:
    """Return the bounded continuation package for the current rejection case."""
    bridge = build_rejection_continuation_bridge(messages)
    if bridge is None:
        return None
    tool_name = bridge.metadata.get("tool_name")
    source_note = None
    if messages:
        source_note = messages[-1].metadata.get("note") if isinstance(messages[-1].metadata, dict) else None
    return ContinuationContextPackage(
        context_kind="approval_rejection",
        bridge_message=bridge,
        system_prompt=build_next_allowed_actions_system_prompt(tool_name=tool_name, note=source_note),
        allowed_next_actions=list(DEFAULT_REJECTION_ALLOWED_NEXT_ACTIONS),
        metadata={
            "tool_name": tool_name,
            "tool_executed": False,
            "source_message_kind": "approval_decision",
        },
    )
