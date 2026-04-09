from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from orbit.models import ConversationMessage, MessageRole
from orbit.runtime.core.outcomes import ResolvedRuntimeTarget


@dataclass
class RuntimeContinuationPlan:
    mutations_before_continue: list[dict[str, Any]] = field(default_factory=list)
    mutations_on_stale: list[dict[str, Any]] = field(default_factory=list)
    mutations_after_settle: list[dict[str, Any]] = field(default_factory=list)
    stale: bool = False


class RuntimeContinuationPlanner:
    def build(
        self,
        *,
        target: ResolvedRuntimeTarget,
        messages: list[ConversationMessage],
        pending: dict[str, Any],
    ) -> RuntimeContinuationPlan:
        target_id = target.target_id
        acceptance_turn_index = pending.get("acceptance_turn_index")
        stale = isinstance(acceptance_turn_index, int) and len(messages) != acceptance_turn_index + 1
        if stale:
            return RuntimeContinuationPlan(
                stale=True,
                mutations_on_stale=[
                    {
                        "kind": "merge_dict",
                        "target": {"scope": target.anchor_scope, "key": str(target.anchor_handle.get("pending_key") or "pending_handoff"), "target_id": target_id},
                        "value": {
                            "status": "result_discarded_as_stale",
                            "discard_reason": "session_advanced_after_handoff",
                            "discarded_result_request_id": target_id,
                            "continuation_state": "discarded_as_stale",
                            "session_turn_state": "turn_closed_continuation_discarded",
                        },
                    },
                    {
                        "kind": "merge_dict",
                        "target": {"scope": target.anchor_scope, "key": str(target.anchor_handle.get("active_key") or "active_continuation"), "target_id": target_id},
                        "value": {
                            "status": "result_discarded_as_stale",
                            "discard_reason": "session_advanced_after_handoff",
                            "discarded_result_request_id": target_id,
                            "continuation_state": "discarded_as_stale",
                            "session_turn_state": "turn_closed_continuation_discarded",
                        },
                    },
                    {
                        "kind": "set_scalar",
                        "target": {"scope": "operation_metadata", "key": "session_activity"},
                        "value": "continuation_discarded",
                    },
                ],
            )
        return RuntimeContinuationPlan(
            stale=False,
            mutations_before_continue=[
                {
                    "kind": "merge_dict",
                    "target": {"scope": target.anchor_scope, "key": str(target.anchor_handle.get("pending_key") or "pending_handoff"), "target_id": target_id},
                    "value": {
                        "status": "result_ingested",
                        "result_request_id": target_id,
                        "result_ingested_at": datetime.now(timezone.utc).isoformat(),
                        "continuation_state": "result_ingested",
                        "session_turn_state": "turn_reopening_from_capability_result",
                    },
                },
                {
                    "kind": "merge_dict",
                    "target": {"scope": target.anchor_scope, "key": str(target.anchor_handle.get("active_key") or "active_continuation"), "target_id": target_id},
                    "value": {
                        "status": "result_ingested",
                        "result_request_id": target_id,
                        "result_ingested_at": datetime.now(timezone.utc).isoformat(),
                        "continuation_state": "result_ingested",
                        "session_turn_state": "turn_reopening_from_capability_result",
                    },
                },
                {
                    "kind": "set_scalar",
                    "target": {"scope": "operation_metadata", "key": "session_activity"},
                    "value": "continuation_reopening_turn",
                },
            ],
            mutations_after_settle=[
                {
                    "kind": "merge_dict",
                    "target": {"scope": target.anchor_scope, "key": str(target.anchor_handle.get("active_key") or "active_continuation"), "target_id": target_id},
                    "value": {
                        "continuation_state": "settled",
                        "session_turn_state": "turn_reclosed_after_capability_result",
                        "settled_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
                {
                    "kind": "set_scalar",
                    "target": {"scope": "operation_metadata", "key": "session_activity"},
                    "value": "idle",
                },
            ],
        )
