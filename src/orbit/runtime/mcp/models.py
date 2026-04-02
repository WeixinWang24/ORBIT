from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


McpTransportKind = Literal["stdio"]


@dataclass
class McpStdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class McpClientBootstrap:
    server_name: str
    normalized_name: str
    tool_prefix: str
    transport: McpTransportKind
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class McpToolDescriptor:
    server_name: str
    original_name: str
    orbit_tool_name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
