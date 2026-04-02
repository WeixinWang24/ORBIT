from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class McpResourceDescriptor:
    server_name: str
    resource_uri: str
    resource_name: str
    description: str | None = None
    mime_type: str | None = None


@dataclass
class McpResourceContent:
    uri: str
    mime_type: str | None
    text: str | None = None
    blob: str | None = None
    raw_item: dict[str, Any] | None = None
