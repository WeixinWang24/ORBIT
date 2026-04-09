from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawRuntimeOutcome:
    outcome_id: str
    outcome_scope: str
    patch_target: dict[str, Any]
    canonical_patch: dict[str, Any] = field(default_factory=dict)
    transcript_entry: dict[str, Any] | None = None
    continuation_action: str = "continue"
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedRuntimeTarget:
    target_kind: str
    target_id: str
    anchor_scope: str
    anchor_handle: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeContinuationDirective:
    kind: str
    activity: str | None = None
    continue_turn: bool = False
    append_transcript: bool = True


@dataclass
class ResolvedRuntimeOutcome:
    outcome_id: str
    outcome_scope: str
    resolved_target: ResolvedRuntimeTarget
    canonical_patch: dict[str, Any] = field(default_factory=dict)
    transcript_entry: dict[str, Any] | None = None
    continuation_directive: RuntimeContinuationDirective = field(
        default_factory=lambda: RuntimeContinuationDirective(kind="hold", activity="paused", continue_turn=False)
    )
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
