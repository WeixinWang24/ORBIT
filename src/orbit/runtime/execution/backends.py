"""Execution backend boundary for ORBIT runtime planning.

This module introduces the first code-level execution backend interface for
ORBIT. The immediate goal is to preserve the existing dummy-first scaffold
while creating a narrow, explicit place where future live model backends can be
added without letting provider logic leak into the coordinator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.engines.dummy_engine import DummyEngine
from orbit.runtime.execution.contracts.plans import ExecutionPlan


class ExecutionBackend(ABC):
    """Abstract execution backend interface for ORBIT.

    The backend boundary is intentionally small in the current phase: given a
    run descriptor, produce a bounded execution plan. This keeps the coordinator
    responsible for governed runtime flow while leaving execution-source details
    outside the coordinator.
    """

    backend_name: str = "abstract"

    @abstractmethod
    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        """Produce the next bounded execution plan for a run descriptor."""


class DummyExecutionBackend(ExecutionBackend):
    """Execution backend adapter over the existing deterministic dummy engine."""

    backend_name = "dummy"

    def __init__(self):
        """Initialize the dummy backend with the deterministic dummy engine."""
        self.engine = DummyEngine()

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        """Return the deterministic dummy plan for the supplied descriptor."""
        return self.engine.plan(descriptor)


class SshVllmExecutionBackend(ExecutionBackend):
    """Planned V1 execution backend placeholder for SSH-mediated vLLM.

    This class is intentionally a placeholder. It exists to reserve the narrow
    V1 live model boundary in code while keeping provider implementation out of
    the coordinator until later work begins.
    """

    backend_name = "ssh-vllm"

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        """Raise until the SSH vLLM backend is explicitly implemented."""
        raise NotImplementedError("SSH vLLM execution backend is not implemented yet")
