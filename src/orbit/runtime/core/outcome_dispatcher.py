from __future__ import annotations

from orbit.models import ConversationSession
from orbit.runtime.core.outcomes import (
    RawRuntimeOutcome,
    ResolvedRuntimeOutcome,
    ResolvedRuntimeTarget,
    RuntimeContinuationDirective,
)


class RuntimeOutcomeDispatcher:
    def resolve(self, *, session: ConversationSession, outcome: RawRuntimeOutcome) -> ResolvedRuntimeOutcome:
        target = self._resolve_target(session=session, patch_target=outcome.patch_target)
        directive = self._resolve_continuation_directive(outcome=outcome)
        return ResolvedRuntimeOutcome(
            outcome_id=outcome.outcome_id,
            outcome_scope=outcome.outcome_scope,
            resolved_target=target,
            canonical_patch=outcome.canonical_patch,
            canonical_mutations=self._resolve_canonical_mutations(target=target, outcome=outcome, directive=directive),
            transcript_entry=outcome.transcript_entry,
            continuation_directive=directive,
            content=outcome.content,
            data=outcome.data,
        )

    def _resolve_target(self, *, session: ConversationSession, patch_target: dict) -> ResolvedRuntimeTarget:
        target_kind = patch_target.get("target_kind")
        target_id = patch_target.get("target_id")
        if target_kind != "capability_handoff" or not isinstance(target_id, str) or not target_id:
            raise ValueError(f"unsupported runtime outcome patch target: {patch_target}")
        return ResolvedRuntimeTarget(
            target_kind="capability_handoff",
            target_id=target_id,
            anchor_scope="capability_metadata",
            anchor_handle={"pending_key": "pending_handoff", "active_key": "active_continuation"},
        )

    def _resolve_canonical_mutations(
        self,
        *,
        target: ResolvedRuntimeTarget,
        outcome: RawRuntimeOutcome,
        directive: RuntimeContinuationDirective,
    ) -> list[dict]:
        mutations: list[dict] = []
        pending_patch = outcome.canonical_patch.get("pending_handoff") if isinstance(outcome.canonical_patch.get("pending_handoff"), dict) else None
        if pending_patch is not None:
            mutations.append(
                {
                    "kind": "merge_dict",
                    "target": {
                        "scope": target.anchor_scope,
                        "key": str(target.anchor_handle.get("pending_key") or "pending_handoff"),
                        "target_id": target.target_id,
                    },
                    "value": pending_patch,
                }
            )
            mutations.append(
                {
                    "kind": "merge_dict",
                    "target": {
                        "scope": target.anchor_scope,
                        "key": str(target.anchor_handle.get("active_key") or "active_continuation"),
                        "target_id": target.target_id,
                    },
                    "value": pending_patch,
                }
            )
        pending_approval_patch = outcome.canonical_patch.get("pending_approval") if isinstance(outcome.canonical_patch.get("pending_approval"), dict) else None
        if pending_approval_patch is not None:
            mutations.append(
                {
                    "kind": "set_dict",
                    "target": {
                        "scope": target.anchor_scope,
                        "key": "pending_approval",
                        "target_id": target.target_id,
                    },
                    "value": {
                        "capability_request_id": target.target_id,
                        **pending_approval_patch,
                    },
                }
            )
        if directive.activity is not None:
            mutations.append(
                {
                    "kind": "set_scalar",
                    "target": {
                        "scope": "operation_metadata",
                        "key": "session_activity",
                    },
                    "value": directive.activity,
                }
            )
        return mutations

    def _resolve_continuation_directive(self, *, outcome: RawRuntimeOutcome) -> RuntimeContinuationDirective:
        pending_patch = outcome.canonical_patch.get("pending_handoff") if isinstance(outcome.canonical_patch.get("pending_handoff"), dict) else None
        if outcome.continuation_action == "continue":
            return RuntimeContinuationDirective(
                kind="continue",
                activity="continuation_reopening_turn",
                continue_turn=True,
                append_transcript=False,
            )
        if isinstance(pending_patch, dict):
            status = pending_patch.get("status")
            governance_outcome = pending_patch.get("governance_outcome") if isinstance(pending_patch.get("governance_outcome"), dict) else None
            if status == "waiting_for_approval":
                return RuntimeContinuationDirective(
                    kind="hold",
                    activity="waiting_for_approval",
                    continue_turn=False,
                    append_transcript=True,
                )
            if status == "detached":
                return RuntimeContinuationDirective(
                    kind="hold",
                    activity="detached",
                    continue_turn=False,
                    append_transcript=True,
                )
            if status == "governance_blocked" and isinstance(governance_outcome, dict):
                substrate_result = governance_outcome.get("substrate_result") if isinstance(governance_outcome.get("substrate_result"), dict) else None
                runtime_result = governance_outcome.get("runtime_result") if isinstance(governance_outcome.get("runtime_result"), dict) else None
                if isinstance(substrate_result, dict) and substrate_result.get("decision") in {"denied", "constrained"}:
                    return RuntimeContinuationDirective(
                        kind="hold",
                        activity="substrate_blocked",
                        continue_turn=False,
                        append_transcript=True,
                    )
                if isinstance(runtime_result, dict) and runtime_result.get("decision") == "deny":
                    return RuntimeContinuationDirective(
                        kind="hold",
                        activity="governance_blocked",
                        continue_turn=False,
                        append_transcript=True,
                    )
        return RuntimeContinuationDirective(
            kind="hold",
            activity="paused",
            continue_turn=False,
            append_transcript=True,
        )
