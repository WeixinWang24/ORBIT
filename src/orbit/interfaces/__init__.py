"""Isolated interface layer for ORBIT Web UI and CLI surfaces.

This package exists to let interface work proceed independently from the
currently active runtime / MCP / tool-capability implementation work.

Current posture:
- use adapter-shaped boundaries
- support mock-driven Web UI and CLI development
- avoid coupling first-wave interface work directly into SessionManager or the
  existing web inspector implementation
"""

from .contracts import (
    InterfaceApproval,
    InterfaceArtifact,
    InterfaceEvent,
    InterfaceMessage,
    InterfaceSession,
    InterfaceToolCall,
    OrbitInterfaceAdapter,
)

__all__ = [
    "InterfaceApproval",
    "InterfaceArtifact",
    "InterfaceEvent",
    "InterfaceMessage",
    "InterfaceSession",
    "InterfaceToolCall",
    "OrbitInterfaceAdapter",
]
