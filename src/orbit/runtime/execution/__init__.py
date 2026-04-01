"""Execution-layer contracts and helpers for ORBIT runtime."""

from orbit.runtime.execution.backends import DummyExecutionBackend, ExecutionBackend
from orbit.runtime.execution.contracts import ExecutionPlan, OpenAIFirstRawResponse, OpenAIFirstRequest, OpenAIRawOutputItem, ToolRequest
from orbit.runtime.execution.engines import DummyEngine
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan

__all__ = [
    "DummyEngine",
    "DummyExecutionBackend",
    "ExecutionBackend",
    "ExecutionPlan",
    "OpenAIFirstRawResponse",
    "OpenAIFirstRequest",
    "OpenAIRawOutputItem",
    "ProviderFailure",
    "ProviderNormalizedResult",
    "ToolRequest",
    "normalized_result_to_execution_plan",
]
