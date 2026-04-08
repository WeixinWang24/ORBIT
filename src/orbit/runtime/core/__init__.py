"""Core runtime coordination structures for ORBIT.

Mainline core:
- `SessionManager`

Historical coordinator scaffolds have been removed from the active codebase.
"""

from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.core.events import RuntimeEventType
from orbit.runtime.core.session_manager import SessionManager

__all__ = ["SessionManager", "RunDescriptor", "RuntimeEventType"]
