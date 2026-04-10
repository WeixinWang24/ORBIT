from __future__ import annotations

from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig, build_codex_session_manager_for_profile
from orbit.interfaces.runtime_profile import resolve_runtime_profile


def test_runtime_adapter_contract_surface_is_declared() -> None:
    config = RuntimeAdapterConfig()
    assert config.model == "gpt-5.4"
    assert config.runtime_profile == "runtime_core_minimal"


def test_runtime_adapter_mcp_default_profile_mounts_filesystem_only() -> None:
    config = RuntimeAdapterConfig.mcp_default(runtime_mode="evo")
    spec = config.resolve_spec()
    assert config.runtime_mode == "evo"
    assert config.runtime_profile == "mcp_default"
    assert spec.name == "mcp_default"
    assert spec.enable_tools is True
    assert spec.capability_profile.filesystem is True
    assert spec.capability_profile.git is False
    assert spec.capability_profile.bash is False
    assert spec.capability_profile.process is False
    assert spec.capability_profile.pytest is False
    assert spec.capability_profile.ruff is False
    assert spec.capability_profile.mypy is False
    assert spec.capability_profile.browser is False
    assert spec.capability_profile.obsidian is False
    assert spec.knowledge_augmentation is False
    assert spec.memory is False


def test_profile_first_builder_prefers_named_profile_entry() -> None:
    spec = resolve_runtime_profile("mcp_default", runtime_mode="evo")
    manager, _composer, bundle = build_codex_session_manager_for_profile(profile=spec)
    assert manager.runtime_mode == "evo"
    assert manager.metadata["runtime_profile"] == "mcp_default"
    assert "filesystem" in bundle.enabled_capabilities
    assert "git" not in bundle.enabled_capabilities


def test_profile_first_builder_supports_runtime_core_minimal_name() -> None:
    spec = resolve_runtime_profile("runtime_core_minimal", runtime_mode="evo")
    manager, _composer, bundle = build_codex_session_manager_for_profile(profile=spec)
    assert manager.runtime_mode == "evo"
    assert manager.metadata["runtime_profile"] == "runtime_core_minimal"
    assert bundle.enabled_capabilities == set()
