from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Thread
from typing import Protocol, Any

from orbit.models import ConversationSession
from orbit.models.core import new_id
from orbit.runtime.execution.contracts.plans import ExecutionPlan, ToolRequest
from orbit.runtime.core.outcomes import RawRuntimeOutcome
from orbit.runtime.extensions.capability_attach import CapabilityGovernanceStack, DetachedCapabilityGovernanceStack
from orbit.runtime.extensions.capability_registry import CapabilityToolRegistry, RegistryBackedCapabilityToolRegistry
from orbit.runtime.extensions.metadata_channels import capability_metadata
from orbit.tools.registry import ToolRegistry


@dataclass
class CapabilityDescriptor:
    name: str
    kind: str = "tool"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilitySurfaceSnapshot:
    capabilities: list[CapabilityDescriptor]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityHandoff:
    capability_request_id: str
    status: str
    tool_projection: dict[str, Any]
    message: str
    source: str


@dataclass
class CapabilityExecutionResult(RawRuntimeOutcome):
    tool_projection: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    source: str = "capability_surface"


class CapabilitySurface(Protocol):
    def snapshot(self, *, runtime_profile: str) -> CapabilitySurfaceSnapshot:
        ...

    def list_tool_names(self, *, runtime_profile: str) -> list[str]:
        ...

    def submit_handoff(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityHandoff:
        ...

    def consume_handoff(
        self,
        *,
        session: ConversationSession,
        capability_request_id: str,
        result_callback,
    ) -> CapabilityExecutionResult:
        ...


def _store_pending_handoff(*, session: ConversationSession, capability_request_id: str, plan: ExecutionPlan, runtime_profile: str, tool_projection: dict[str, Any] | None = None) -> None:
    capability_metadata(session.metadata)["pending_handoff"] = {
        "capability_request_id": capability_request_id,
        "tool_projection": dict(tool_projection or {}),
        "input_payload": plan.tool_request.input_payload,
        "provider_call_id": plan.tool_request.provider_call_id,
        "runtime_profile": runtime_profile,
        "status": "handoff_recorded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class CapabilitySurfaceRunner:
    def __init__(self, *, session_manager, capability_surface: CapabilitySurface, outcome_dispatcher):
        self.session_manager = session_manager
        self.capability_surface = capability_surface
        self.outcome_dispatcher = outcome_dispatcher

    def consume_handoff_async(self, *, session_id: str, capability_request_id: str) -> Thread:
        def _run() -> None:
            session = self.session_manager.get_session(session_id)
            if session is None:
                return
            self.capability_surface.consume_handoff(
                session=session,
                capability_request_id=capability_request_id,
                result_callback=lambda result: self.session_manager.apply_runtime_outcome(
                    session_id=session_id,
                    outcome=self.outcome_dispatcher.resolve(session=session, outcome=result),
                ),
            )

        thread = Thread(target=_run, name=f"capability-handoff-{capability_request_id}", daemon=True)
        thread.start()
        return thread


class NoOpCapabilitySurface:
    def snapshot(self, *, runtime_profile: str) -> CapabilitySurfaceSnapshot:
        return CapabilitySurfaceSnapshot(capabilities=[], metadata={"runtime_profile": runtime_profile, "surface_state": "detached"})

    def list_tool_names(self, *, runtime_profile: str) -> list[str]:
        return []

    def submit_handoff(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityHandoff:
        if plan.tool_request is None:
            raise ValueError("cannot submit capability handoff without a tool request")
        capability_request_id = new_id("capreq")
        tool_projection = {
            "tool_name": plan.tool_request.tool_name,
            "side_effect_class": plan.tool_request.side_effect_class,
            "requires_approval": plan.tool_request.requires_approval,
            "source": "detached",
            "metadata": {},
        }
        _store_pending_handoff(session=session, capability_request_id=capability_request_id, plan=plan, runtime_profile=runtime_profile, tool_projection=tool_projection)
        return CapabilityHandoff(
            capability_request_id=capability_request_id,
            status="handoff_recorded",
            tool_projection=tool_projection,
            message="Tool request handed off to capability surface; execution remains detached in current runtime-core mode.",
            source="no_op_capability_surface",
        )

    def consume_handoff(
        self,
        *,
        session: ConversationSession,
        capability_request_id: str,
        result_callback,
    ) -> CapabilityExecutionResult:
        pending = capability_metadata(session.metadata).get("pending_handoff")
        if not isinstance(pending, dict) or pending.get("capability_request_id") != capability_request_id:
            raise ValueError(f"capability handoff not found: {capability_request_id}")
        tool_projection = pending.get("tool_projection") if isinstance(pending.get("tool_projection"), dict) else {}
        result = CapabilityExecutionResult(
            outcome_id=capability_request_id,
            outcome_scope="capability",
            patch_target={"target_kind": "capability_handoff", "target_id": capability_request_id},
            tool_projection=tool_projection,
            ok=False,
            content="Capability execution remains detached on the no-op capability surface.",
            data={"tool_projection": tool_projection},
            canonical_patch={
                "pending_handoff": {
                    "status": "detached",
                    "tool_projection": tool_projection,
                }
            },
            transcript_entry={
                "role": "tool",
                "content": "Capability execution remains detached on the no-op capability surface.",
                "metadata": {
                    "message_kind": "capability_result",
                    "capability_request_id": capability_request_id,
                    "tool_projection": tool_projection,
                },
            },
            continuation_action="hold",
            source="no_op_capability_surface",
        )
        result_callback(result)
        return result


class RegistryBackedCapabilitySurface:
    def __init__(self, *, tool_registry: ToolRegistry | None = None, capability_tool_registry: CapabilityToolRegistry | None = None, governance_stack: CapabilityGovernanceStack | None = None, enabled_capabilities: set[str] | None = None):
        self.tool_registry = tool_registry
        self.capability_tool_registry = capability_tool_registry or (RegistryBackedCapabilityToolRegistry(tool_registry=tool_registry) if tool_registry is not None else None)
        self.governance_stack = governance_stack or DetachedCapabilityGovernanceStack()
        self.enabled_capabilities = enabled_capabilities or set()

    def snapshot(self, *, runtime_profile: str) -> CapabilitySurfaceSnapshot:
        registry = self.capability_tool_registry
        if registry is None:
            return CapabilitySurfaceSnapshot(capabilities=[], metadata={"runtime_profile": runtime_profile, "surface_state": "detached"})
        capabilities = [
            CapabilityDescriptor(
                name=tool.name,
                kind="tool",
                metadata={
                    "side_effect_class": tool.side_effect_class,
                    "requires_approval": tool.requires_approval,
                    "source": tool.source,
                    **tool.metadata,
                },
            )
            for tool in registry.list_tool_descriptors()
        ]
        return CapabilitySurfaceSnapshot(
            capabilities=capabilities,
            metadata={
                "runtime_profile": runtime_profile,
                "surface_state": "attached",
                "enabled_capabilities": sorted(self.enabled_capabilities),
            },
        )

    def list_tool_names(self, *, runtime_profile: str) -> list[str]:
        snap = self.snapshot(runtime_profile=runtime_profile)
        return [item.name for item in snap.capabilities]

    def submit_handoff(
        self,
        *,
        session: ConversationSession,
        plan: ExecutionPlan,
        runtime_profile: str,
    ) -> CapabilityHandoff:
        if plan.tool_request is None:
            raise ValueError("cannot submit capability handoff without a tool request")
        capability_request_id = new_id("capreq")
        descriptor = self.capability_tool_registry.get_tool_descriptor(plan.tool_request.tool_name) if self.capability_tool_registry is not None else None
        tool_projection = descriptor.model_dump() if descriptor is not None else {
            "tool_name": plan.tool_request.tool_name,
            "side_effect_class": plan.tool_request.side_effect_class,
            "requires_approval": plan.tool_request.requires_approval,
            "source": "unknown",
            "metadata": {},
        }
        _store_pending_handoff(session=session, capability_request_id=capability_request_id, plan=plan, runtime_profile=runtime_profile, tool_projection=tool_projection)
        return CapabilityHandoff(
            capability_request_id=capability_request_id,
            status="handoff_recorded",
            tool_projection=tool_projection,
            message="Tool request handed off to capability surface.",
            source="registry_backed_capability_surface",
        )

    def consume_handoff(
        self,
        *,
        session: ConversationSession,
        capability_request_id: str,
        result_callback,
    ) -> CapabilityExecutionResult:
        pending = capability_metadata(session.metadata).get("pending_handoff")
        if not isinstance(pending, dict) or pending.get("capability_request_id") != capability_request_id:
            raise ValueError(f"capability handoff not found: {capability_request_id}")
        registry = self.capability_tool_registry
        if registry is None:
            raise ValueError("registry-backed capability surface has no capability tool registry")
        tool_projection = pending.get("tool_projection") if isinstance(pending.get("tool_projection"), dict) else {}
        tool_name = str(tool_projection.get("tool_name") or "")
        input_payload = pending.get("input_payload") if isinstance(pending.get("input_payload"), dict) else {}
        descriptor = registry.get_tool_descriptor(tool_name)
        governance = self.governance_stack.evaluate(
            session=session,
            plan=ExecutionPlan(
                source_backend="capability_surface",
                plan_label="capability-governance-evaluation",
                tool_request=ToolRequest(
                    tool_name=tool_name,
                    input_payload=input_payload,
                    requires_approval=descriptor.requires_approval,
                    side_effect_class=descriptor.side_effect_class,
                    provider_call_id=pending.get("provider_call_id"),
                ),
            ),
            runtime_profile=str(pending.get("runtime_profile") or "runtime_core_minimal"),
            tool_projection=descriptor.model_dump(),
            input_payload=input_payload,
        )
        governance_outcome = {
            "runtime_result": governance.runtime_result.__dict__,
            "substrate_result": governance.substrate_result.__dict__,
            "effective_outcome": governance.effective_outcome,
            "notes": governance.notes or {},
        }
        if governance.effective_outcome != "execute":
            blocked_content = governance.runtime_result.note or governance.runtime_result.reason
            if governance.substrate_result.decision in {"denied", "constrained"}:
                blocked_content = governance.substrate_result.reason
            elif governance.runtime_result.decision == "await_approval":
                blocked_content = governance.runtime_result.note or "approval_required"
            result = CapabilityExecutionResult(
                outcome_id=capability_request_id,
                outcome_scope="capability",
                patch_target={"target_kind": "capability_handoff", "target_id": capability_request_id},
                tool_projection=descriptor.model_dump(),
                ok=False,
                content=blocked_content,
                data={
                    "tool_projection": descriptor.model_dump(),
                    "governance_outcome": governance_outcome,
                },
                canonical_patch={
                    "pending_handoff": {
                        "governance_outcome": governance_outcome,
                        "status": "waiting_for_approval" if governance.runtime_result.decision == "await_approval" else "governance_blocked",
                        "tool_projection": descriptor.model_dump(),
                    },
                    "pending_approval": {
                        "tool_projection": descriptor.model_dump(),
                        "input_payload": input_payload,
                        "governance_outcome": governance_outcome,
                    } if governance.runtime_result.decision == "await_approval" else None,
                },
                transcript_entry={
                    "role": "tool",
                    "content": blocked_content,
                    "metadata": {
                        "message_kind": "capability_result",
                        "capability_request_id": capability_request_id,
                        "provider_call_id": pending.get("provider_call_id"),
                        "tool_projection": descriptor.model_dump(),
                    },
                },
                continuation_action="hold",
                source="registry_backed_capability_surface",
            )
            result_callback(result)
            return result
        tool = registry.get_tool(tool_name)
        tool_result = tool.invoke(**input_payload)
        result = CapabilityExecutionResult(
            outcome_id=capability_request_id,
            outcome_scope="capability",
            patch_target={"target_kind": "capability_handoff", "target_id": capability_request_id},
            tool_projection=descriptor.model_dump(),
            ok=tool_result.ok,
            content=tool_result.content,
            data={
                **(tool_result.data or {}),
                "tool_projection": descriptor.model_dump(),
            },
            canonical_patch={
                "pending_handoff": {
                    "governance_outcome": governance_outcome,
                    "status": "executed",
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "result_ok": bool(tool_result.ok),
                    "tool_projection": descriptor.model_dump(),
                }
            },
            continuation_action="continue",
            source="registry_backed_capability_surface",
        )
        result_callback(result)
        return result
