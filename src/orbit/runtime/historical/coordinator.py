"""Runtime coordination for ORBIT governed runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orbit.models import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalRequestStatus,
    ContextArtifact,
    ConversationMessage,
    ConversationSession,
    ExecutionEvent,
    Run,
    RunStatus,
    RunStep,
    StepStatus,
    StepType,
    Task,
    TaskStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from orbit.runtime.core.contracts import RunDescriptor, WorkspaceDescriptor
from orbit.runtime.core.events import RuntimeEventType
from orbit.runtime.core.session_manager import SessionManager
from orbit.runtime.execution.backends import DummyExecutionBackend, ExecutionBackend
from orbit.store.base import OrbitStore
from orbit.tools import ToolRegistry


class OrbitCoordinator:
    """Coordinate explicit ORBIT runtime flows against a persistence store."""

    def __init__(self, store: OrbitStore, workspace_root: Path, backend: ExecutionBackend | None = None):
        self.store = store
        self.workspace_root = workspace_root
        self.tools = ToolRegistry(workspace_root)
        self.backend = backend or DummyExecutionBackend()
        self.session_manager = SessionManager(store=store, backend=self.backend, workspace_root=str(workspace_root))

    def create_task(self, title: str, description: str) -> Task:
        task = Task(title=title, description=description, status=TaskStatus.READY)
        self.store.save_task(task)
        return task

    def create_session(self, *, backend_name: str, model: str, conversation_id: str | None = None) -> ConversationSession:
        """Create a new multi-turn non-tool conversation session."""
        return self.session_manager.create_session(backend_name=backend_name, model=model, conversation_id=conversation_id)

    def run_session_turn(self, *, session_id: str, user_input: str) -> ExecutionPlan:
        """Execute one session turn through the first session-manager scaffold."""
        return self.session_manager.run_session_turn(session_id=session_id, user_input=user_input)

    def inspect_session(self, session_id: str) -> dict:
        """Return a compact inspection bundle for one session."""
        session = self.session_manager.get_session(session_id)
        messages = self.session_manager.list_messages(session_id)
        return {"session": session, "messages": messages}

    def build_run_descriptor(self, task: Task, user_input: str, dummy_scenario: str) -> RunDescriptor:
        return RunDescriptor(
            session_key=f"session:{task.task_id}",
            conversation_id=f"conversation:{task.task_id}",
            workspace=WorkspaceDescriptor(cwd=str(self.workspace_root), writable_roots=[str(self.workspace_root)]),
            user_input=user_input,
            dummy_scenario=dummy_scenario,
        )

    def start_run(self, task: Task, descriptor: RunDescriptor) -> Run:
        run = Run(run_id=descriptor.run_id, task_id=task.task_id, status=RunStatus.RUNNING, started_at=datetime.now(timezone.utc))
        self.store.save_run(run)
        self._emit(run.run_id, RuntimeEventType.RUN_CREATED, {"task_id": task.task_id, "session_key": descriptor.session_key, "backend": self.backend.backend_name})
        self._emit(run.run_id, RuntimeEventType.RUN_STARTED, {"user_input": descriptor.user_input, "dummy_scenario": descriptor.dummy_scenario, "backend": self.backend.backend_name})
        self.store.save_context_artifact(ContextArtifact(run_id=run.run_id, artifact_type="task_brief", content=descriptor.user_input, source="user_input"))
        self.store.save_context_artifact(ContextArtifact(run_id=run.run_id, artifact_type="run_descriptor", content=descriptor.model_dump_json(indent=2), source="runtime_contract"))
        return run

    def run_dummy_scenario(self, title: str, description: str, user_input: str, dummy_scenario: str) -> Run:
        task = self.create_task(title=title, description=description)
        descriptor = self.build_run_descriptor(task, user_input, dummy_scenario)
        run = self.start_run(task, descriptor)
        self._complete_step(self._start_step(run, StepType.CONTEXT_ASSEMBLY, 1))
        self._complete_step(self._start_step(run, StepType.MODEL_GENERATION, 2))
        plan = self.backend.plan(descriptor)
        self._emit(run.run_id, RuntimeEventType.DUMMY_PLAN_SELECTED, {"plan_label": plan.plan_label, "backend": plan.source_backend})
        if plan.failure_reason is not None:
            return self._fail_run(run, 3, plan.failure_reason)
        if plan.tool_request is not None:
            tool_step = self._start_step(run, StepType.TOOL_EXECUTION, 3)
            tool = ToolInvocation(run_id=run.run_id, step_id=tool_step.step_id, tool_name=plan.tool_request.tool_name, input_payload=plan.tool_request.input_payload, status=ToolInvocationStatus.REQUESTED, side_effect_class=plan.tool_request.side_effect_class)
            self.store.save_tool_invocation(tool)
            self._emit(run.run_id, RuntimeEventType.TOOL_INVOCATION_REQUESTED, {"tool_name": tool.tool_name, "plan_label": plan.plan_label, "backend": plan.source_backend}, step_id=tool_step.step_id)
            if plan.tool_request.requires_approval:
                approval = ApprovalRequest(run_id=run.run_id, step_id=tool_step.step_id, target_type="tool_invocation", target_id=tool.tool_invocation_id, reason=f"{tool.tool_name} is side-effecting in plan {plan.plan_label}", risk_level="review_required", status=ApprovalRequestStatus.OPEN)
                self.store.save_approval_request(approval)
                run.status = RunStatus.WAITING_FOR_APPROVAL
                run.current_step_id = tool_step.step_id
                self.store.save_run(run)
                self._emit(run.run_id, RuntimeEventType.APPROVAL_REQUESTED, {"approval_request_id": approval.approval_request_id}, step_id=tool_step.step_id)
                return run
            self._execute_tool_invocation(run, tool_step, tool)
        return self._complete_run(run, 4, plan.final_text or "execution flow completed")

    def list_open_approvals(self) -> list[ApprovalRequest]:
        return self.store.list_open_approval_requests()

    def resolve_approval(self, approval_request_id: str, decision: str, note: str | None = None) -> Run:
        approval = self.store.get_approval_request(approval_request_id)
        if approval is None:
            raise ValueError(f"approval request not found: {approval_request_id}")
        if approval.status != ApprovalRequestStatus.OPEN:
            raise ValueError(f"approval request is not open: {approval_request_id}")
        run = self.store.get_run(approval.run_id)
        if run is None:
            raise ValueError(f"run not found for approval request: {approval.run_id}")
        latest_step = self.store.get_latest_step_for_run(run.run_id)
        if latest_step is None:
            raise ValueError(f"latest step not found for run: {run.run_id}")
        if decision == "approve":
            approval.status = ApprovalRequestStatus.APPROVED
            self.store.save_approval_request(approval)
            approval_decision = ApprovalDecision(approval_request_id=approval.approval_request_id, decision=ApprovalDecisionType.APPROVED, note=note or "approved via scaffold control surface")
            self.store.save_approval_decision(approval_decision)
            self._emit(run.run_id, RuntimeEventType.APPROVAL_GRANTED, {"approval_request_id": approval.approval_request_id}, step_id=approval.step_id)
            tool = self.store.get_tool_invocation(approval.target_id)
            if tool is None:
                raise ValueError(f"tool invocation not found for approval target: {approval.target_id}")
            run.status = RunStatus.RUNNING
            self.store.save_run(run)
            self._execute_tool_invocation(run, latest_step, tool)
            return self._complete_run(run, 4, "Execution flow completed after approval-mediated execution.")
        if decision == "reject":
            approval.status = ApprovalRequestStatus.REJECTED
            self.store.save_approval_request(approval)
            approval_decision = ApprovalDecision(approval_request_id=approval.approval_request_id, decision=ApprovalDecisionType.REJECTED, note=note or "rejected via scaffold control surface")
            self.store.save_approval_decision(approval_decision)
            self._emit(run.run_id, RuntimeEventType.APPROVAL_REJECTED, {"approval_request_id": approval.approval_request_id}, step_id=approval.step_id)
            return self._fail_run(run, latest_step.index + 1, "Approval was rejected")
        raise ValueError(f"unsupported approval decision: {decision}")

    def _execute_tool_invocation(self, run: Run, tool_step: RunStep, tool: ToolInvocation) -> None:
        impl = self.tools.get(tool.tool_name)
        result = impl.invoke(**tool.input_payload)
        tool.status = ToolInvocationStatus.COMPLETED if result.ok else ToolInvocationStatus.FAILED
        tool.result_payload = {"ok": result.ok, "content": result.content, **(result.data or {})}
        tool.started_at = datetime.now(timezone.utc)
        tool.ended_at = datetime.now(timezone.utc)
        self.store.save_tool_invocation(tool)
        self._emit(run.run_id, RuntimeEventType.TOOL_INVOCATION_COMPLETED, {"tool_name": tool.tool_name, "ok": result.ok, "content": result.content}, step_id=tool_step.step_id)
        self._complete_step(tool_step)

    def _complete_run(self, run: Run, result_step_index: int, summary: str) -> Run:
        self._complete_step(self._start_step(run, StepType.RESULT_INCORPORATION, result_step_index))
        term = self._start_step(run, StepType.TERMINATION, result_step_index + 1)
        self._complete_step(term)
        run.status = RunStatus.COMPLETED
        run.ended_at = datetime.now(timezone.utc)
        run.current_step_id = term.step_id
        run.result_summary = summary
        self.store.save_run(run)
        self._emit(run.run_id, RuntimeEventType.RUN_COMPLETED, {"summary": run.result_summary}, step_id=term.step_id)
        return run

    def _fail_run(self, run: Run, termination_index: int, reason: str) -> Run:
        term = self._start_step(run, StepType.TERMINATION, termination_index)
        self._complete_step(term)
        run.status = RunStatus.FAILED
        run.ended_at = datetime.now(timezone.utc)
        run.current_step_id = term.step_id
        run.failure_reason = reason
        run.result_summary = "execution flow failed"
        self.store.save_run(run)
        self._emit(run.run_id, RuntimeEventType.RUN_FAILED, {"reason": reason}, step_id=term.step_id)
        return run

    def _start_step(self, run: Run, step_type: StepType, index: int) -> RunStep:
        step = RunStep(run_id=run.run_id, step_type=step_type, index=index, status=StepStatus.RUNNING, started_at=datetime.now(timezone.utc))
        run.current_step_id = step.step_id
        self.store.save_run(run)
        self.store.save_step(step)
        self._emit(run.run_id, RuntimeEventType.STEP_STARTED, {"step_type": step.step_type}, step_id=step.step_id)
        return step

    def _complete_step(self, step: RunStep) -> None:
        step.status = StepStatus.COMPLETED
        step.ended_at = datetime.now(timezone.utc)
        self.store.save_step(step)
        self._emit(step.run_id, RuntimeEventType.STEP_COMPLETED, {"step_type": step.step_type}, step_id=step.step_id)

    def _emit(self, run_id: str, event_type: RuntimeEventType, payload: dict, step_id: str | None = None) -> None:
        self.store.save_event(ExecutionEvent(run_id=run_id, step_id=step_id, event_type=event_type, payload=payload))
