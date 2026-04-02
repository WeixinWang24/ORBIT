"""Runtime exports for ORBIT.

Mainline runtime surface:
- `SessionManager` is the active session agent loop host module.

Historical/development scaffold surface:
- `OrbitCoordinator` has been moved under `orbit.runtime.historical` for
  teaching and development-history reference.
"""

from orbit.runtime.auth import *
from orbit.runtime.core import RunDescriptor, RuntimeEventType, SessionManager
from orbit.runtime.execution import (
    DummyEngine,
    DummyExecutionBackend,
    ExecutionBackend,
    ExecutionPlan,
    OpenAIFirstRawResponse,
    OpenAIFirstRequest,
    OpenAIRawOutputItem,
    ProviderFailure,
    ProviderNormalizedResult,
    ToolRequest,
    normalized_result_to_execution_plan,
)
from orbit.runtime.providers import *
from orbit.runtime.transports import *

__all__ = [
    "DummyEngine",
    "DummyExecutionBackend",
    "ExecutionBackend",
    "ExecutionPlan",
    "OpenAIFirstRawResponse",
    "OpenAIFirstRequest",
    "OpenAIRawOutputItem",
    "SessionManager",
    "ProviderFailure",
    "ProviderNormalizedResult",
    "RunDescriptor",
    "RuntimeEventType",
    "ToolRequest",
    "normalized_result_to_execution_plan",
]
