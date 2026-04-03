from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from orbit.models.core import OrbitBaseModel


class ToolResult(OrbitBaseModel):
    ok: bool
    content: str
    data: dict[str, Any] | None = None


class Tool(ABC):
    name: str
    side_effect_class: str = "safe"
    requires_approval: bool = False
    governance_policy_group: str = "system_environment"
    environment_check_kind: str = "none"

    def governance_metadata(self) -> dict[str, str]:
        return {
            "policy_group": self.governance_policy_group,
            "environment_check_kind": self.environment_check_kind,
        }

    @abstractmethod
    def invoke(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
