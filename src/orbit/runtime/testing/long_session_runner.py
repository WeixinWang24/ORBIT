"""Minimal long-session scenario runner for ORBIT.

This runner is intentionally small. It is the first step in splitting the
long-session harness into:
- a runtime-facing orchestration core
- a test-bench / sandbox inspection surface

Current scope:
- sequential multi-turn session scenarios
- closure-complete turns through the existing session manager
- lightweight per-turn transcript/state snapshots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from orbit.runtime import SessionManager


@dataclass
class LongSessionScenario:
    """Describe a minimal long-session scenario."""

    name: str
    backend_name: str
    model: str
    turns: list[str]
    workspace_root: Path
    approval_decisions: dict[int, Literal['approve', 'reject']] = field(default_factory=dict)
    expected_last_message_kind_by_turn: dict[int, str] = field(default_factory=dict)
    expect_session_terminated: bool | None = None


@dataclass
class LongSessionTurnResult:
    """Capture one closure-complete turn result."""

    turn_index: int
    user_input: str
    plan: dict[str, Any]
    transcript_count: int
    approval_decision: str | None = None
    governed_tool_state: dict[str, Any] | None = None
    last_message: dict[str, Any] | None = None


@dataclass
class LongSessionScenarioResult:
    """Capture the full result of a long-session scenario run."""

    scenario_name: str
    session_id: str
    backend_name: str
    model: str
    turns: list[LongSessionTurnResult] = field(default_factory=list)
    final_transcript: list[dict[str, Any]] = field(default_factory=list)
    final_governed_tool_state: dict[str, Any] | None = None
    session_terminated: bool = False
    termination_reason: str | None = None


class LongSessionScenarioRunner:
    """Run a minimal closure-complete multi-turn scenario.

    This first version deliberately focuses on safe-tool closure completion so
    LS-01 can become a real multi-turn scenario rather than a repeated first-plan
    probe. Approval-heavy scenarios can be layered on later.
    """

    def validate_result(self, scenario: LongSessionScenario, result: LongSessionScenarioResult) -> list[str]:
        errors: list[str] = []
        for turn in result.turns:
            expected_kind = scenario.expected_last_message_kind_by_turn.get(turn.turn_index)
            actual_kind = None
            if turn.last_message is not None:
                actual_kind = turn.last_message.get('metadata', {}).get('message_kind')
            if expected_kind is not None and actual_kind != expected_kind:
                errors.append(
                    f"turn {turn.turn_index}: expected last_message.metadata.message_kind={expected_kind!r}, got {actual_kind!r}"
                )

        if scenario.expect_session_terminated is not None:
            if result.session_terminated != scenario.expect_session_terminated:
                errors.append(
                    f"expected session_terminated={scenario.expect_session_terminated!r}, got {result.session_terminated!r}"
                )
        return errors

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def _run_turn_to_closure(self, *, session_id: str, user_input: str, approval_decision: str | None = None):
        """Run one turn until it reaches the canonical session-manager boundary.

        Current MVP contract:
        - ``run_session_turn(...)`` is already closure-complete for plain-text and
          non-approval tool turns
        - approval-gated turns return a waiting plan; if a scenario-level decision
          is supplied here, this helper resolves that approval and completes the
          resumed turn through ``resolve_session_approval(...)``
        """
        plan = self.session_manager.run_session_turn(
            session_id=session_id,
            user_input=user_input,
        )
        if plan.tool_request is None or not plan.tool_request.requires_approval:
            return plan
        if approval_decision is None:
            return plan
        approvals = self.session_manager.list_open_session_approvals()
        session_approval = next((item for item in approvals if item['session_id'] == session_id), None)
        if session_approval is None:
            raise ValueError(f"approval decision requested, but no open session approval found: {session_id}")
        return self.session_manager.resolve_session_approval(
            session_id=session_id,
            approval_request_id=session_approval['approval_request_id'],
            decision=approval_decision,
            note=f'{approval_decision}d by long-session runner',
        )

    def run(self, scenario: LongSessionScenario) -> LongSessionScenarioResult:
        session = self.session_manager.create_session(
            backend_name=scenario.backend_name,
            model=scenario.model,
        )
        results: list[LongSessionTurnResult] = []
        for index, user_input in enumerate(scenario.turns, start=1):
            approval_decision = scenario.approval_decisions.get(index)
            plan = self._run_turn_to_closure(
                session_id=session.session_id,
                user_input=user_input,
                approval_decision=approval_decision,
            )
            current_session = self.session_manager.get_session(session.session_id)
            if current_session is None:
                raise ValueError(f"session not found during scenario run: {session.session_id}")
            messages = self.session_manager.list_messages(session.session_id)
            last_message = messages[-1] if messages else None
            results.append(
                LongSessionTurnResult(
                    turn_index=index,
                    user_input=user_input,
                    plan=plan.model_dump(mode='json'),
                    transcript_count=len(messages),
                    approval_decision=approval_decision,
                    governed_tool_state=current_session.governed_tool_state.model_dump(mode='json') if current_session.governed_tool_state else None,
                    last_message={
                        'role': str(last_message.role),
                        'content': last_message.content,
                        'metadata': last_message.metadata,
                    } if last_message else None,
                )
            )

        final_session = self.session_manager.get_session(session.session_id)
        if final_session is None:
            raise ValueError(f"session not found during final scenario inspection: {session.session_id}")
        final_transcript = [
            {
                'role': str(message.role),
                'content': message.content,
                'metadata': message.metadata,
            }
            for message in self.session_manager.list_messages(session.session_id)
        ]
        return LongSessionScenarioResult(
            scenario_name=scenario.name,
            session_id=session.session_id,
            backend_name=scenario.backend_name,
            model=scenario.model,
            turns=results,
            final_transcript=final_transcript,
            final_governed_tool_state=final_session.governed_tool_state.model_dump(mode='json') if final_session.governed_tool_state else None,
            session_terminated=bool(final_session.metadata.get('terminated')),
            termination_reason=final_session.metadata.get('termination_reason'),
        )
