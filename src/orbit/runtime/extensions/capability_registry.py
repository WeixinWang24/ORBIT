from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from orbit.tools.base import Tool
from orbit.tools.registry import ToolRegistry


@dataclass
class CapabilityToolDescriptor:
    name: str
    side_effect_class: str
    requires_approval: bool
    source: str = "native"
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "tool_name": self.name,
            "side_effect_class": self.side_effect_class,
            "requires_approval": self.requires_approval,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


class CapabilityToolRegistry(Protocol):
    def get_tool(self, name: str) -> Tool:
        ...

    def get_tool_descriptor(self, name: str) -> CapabilityToolDescriptor:
        ...

    def list_tool_names(self) -> list[str]:
        ...

    def list_tool_descriptors(self) -> list[CapabilityToolDescriptor]:
        ...

    def build_provider_tool_definitions(self) -> list[dict[str, Any]]:
        ...


class RegistryBackedCapabilityToolRegistry:
    def __init__(self, *, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry

    def get_tool(self, name: str) -> Tool:
        return self.tool_registry.get(name)

    def get_tool_descriptor(self, name: str) -> CapabilityToolDescriptor:
        tool = self.tool_registry.get(name)
        return CapabilityToolDescriptor(
            name=tool.name,
            side_effect_class=getattr(tool, "side_effect_class", "safe"),
            requires_approval=bool(getattr(tool, "requires_approval", False)),
            source=getattr(tool, "tool_source", "native"),
            metadata=tool.governance_metadata(),
        )

    def list_tool_names(self) -> list[str]:
        return self.tool_registry.list_names()

    def list_tool_descriptors(self) -> list[CapabilityToolDescriptor]:
        return [self.get_tool_descriptor(name) for name in self.tool_registry.list_names()]

    def build_provider_tool_definitions(self) -> list[dict[str, Any]]:
        from orbit.runtime.providers.tool_schema_utils import codex_function_definition
        return [codex_function_definition(tool) for tool in self.tool_registry.list_tools()]
