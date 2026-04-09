from __future__ import annotations

from typing import Any


CORE_RUNTIME_KEY = "core_runtime_metadata"
SURFACE_PROJECTION_KEY = "surface_projection_metadata"
OBSERVER_KEY = "observer_metadata"
CAPABILITY_KEY = "capability_metadata"
OPERATION_KEY = "operation_metadata"


def _ensure_channel(container: dict, key: str) -> dict:
    value = container.get(key)
    if isinstance(value, dict):
        return value
    container[key] = {}
    return container[key]


def core_runtime_metadata(container: dict) -> dict:
    return _ensure_channel(container, CORE_RUNTIME_KEY)


def surface_projection_metadata(container: dict) -> dict:
    return _ensure_channel(container, SURFACE_PROJECTION_KEY)


def observer_metadata(container: dict) -> dict:
    return _ensure_channel(container, OBSERVER_KEY)


def capability_metadata(container: dict) -> dict:
    return _ensure_channel(container, CAPABILITY_KEY)


def operation_metadata(container: dict) -> dict:
    return _ensure_channel(container, OPERATION_KEY)


def set_core_runtime_metadata(container: dict, key: str, value: Any) -> None:
    core_runtime_metadata(container)[key] = value


def set_surface_projection_metadata(container: dict, key: str, value: Any) -> None:
    surface_projection_metadata(container)[key] = value


def set_observer_metadata(container: dict, key: str, value: Any) -> None:
    observer_metadata(container)[key] = value


def set_capability_metadata(container: dict, key: str, value: Any) -> None:
    capability_metadata(container)[key] = value


def set_operation_metadata(container: dict, key: str, value: Any) -> None:
    operation_metadata(container)[key] = value
