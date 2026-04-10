from __future__ import annotations

from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig


def test_runtime_adapter_contract_surface_is_declared() -> None:
    config = RuntimeAdapterConfig()
    assert config.model == "gpt-5.4"
    assert config.runtime_profile == "runtime_core_minimal"
    assert config.enable_tools is True
    assert config.filesystem is False
    assert config.bash is False
    assert config.process is False
    assert config.git is False


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
