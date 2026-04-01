from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] | None = None


class Tool(ABC):
    name: str
    side_effect_class: str = "safe"
    requires_approval: bool = False

    @abstractmethod
    def invoke(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
