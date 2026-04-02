"""OrbitCoordinator has moved to ``orbit.runtime.historical.coordinator``.

This active-path location is retired from the runtime mainline.
Import from ``orbit.runtime.historical`` for legacy demos, teaching, and
historical scaffold inspection.
"""

raise ImportError(
    "OrbitCoordinator has been moved to orbit.runtime.historical.coordinator; "
    "the active runtime mainline is SessionManager-centered."
)
