from __future__ import annotations

from pathlib import Path


def _read_pyproject() -> str:
    return Path('/Volumes/2TB/MAS/openclaw-core/ORBIT/pyproject.toml').read_text()


def test_orbit_script_points_to_runtime_workbench() -> None:
    text = _read_pyproject()
    assert 'orbit = "orbit.interfaces.pty_runtime_cli:browse_runtime_cli"' in text


def test_orbit_session_script_points_to_runtime_workbench() -> None:
    text = _read_pyproject()
    assert 'orbit-session = "orbit.interfaces.pty_runtime_cli:browse_runtime_cli"' in text


def test_runtime_workbench_script_points_to_runtime_workbench() -> None:
    text = _read_pyproject()
    assert 'orbit-runtime-workbench = "orbit.interfaces.pty_runtime_cli:browse_runtime_cli"' in text
