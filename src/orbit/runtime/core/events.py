"""Runtime event vocabulary for ORBIT.

This module defines the current named runtime event vocabulary used by the
ORBIT scaffold. Centralizing these names reduces drift and supports the
project's event-first observability goals.
"""

from __future__ import annotations

from enum import Enum


class RuntimeEventType(str, Enum):
    """Named runtime events emitted by the ORBIT execution scaffold."""

    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    DUMMY_PLAN_SELECTED = "dummy_plan_selected"
    TOOL_INVOCATION_REQUESTED = "tool_invocation_requested"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    TOOL_INVOCATION_COMPLETED = "tool_invocation_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
