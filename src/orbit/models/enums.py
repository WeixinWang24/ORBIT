from enum import Enum


class TaskStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepType(str, Enum):
    USER_INPUT = "user_input"
    CONTEXT_ASSEMBLY = "context_assembly"
    MODEL_GENERATION = "model_generation"
    TOOL_PLANNING = "tool_planning"
    APPROVAL_WAIT = "approval_wait"
    TOOL_EXECUTION = "tool_execution"
    RESULT_INCORPORATION = "result_incorporation"
    TERMINATION = "termination"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolInvocationStatus(str, Enum):
    REQUESTED = "requested"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalRequestStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    EXPIRED = "expired"


class ApprovalDecisionType(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
