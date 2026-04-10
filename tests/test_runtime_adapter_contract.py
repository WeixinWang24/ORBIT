from __future__ import annotations

from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig


def test_runtime_adapter_contract_surface_is_declared() -> None:
    config = RuntimeAdapterConfig()
    assert config.model == "gpt-5.4"
    assert config.enable_tools is True
    assert config.filesystem is False
    assert config.bash is False
    assert config.process is False
    assert config.git is False


def test_runtime_adapter_mcp_default_profile_mounts_filesystem_only() -> None:
    config = RuntimeAdapterConfig.mcp_default(runtime_mode="evo")
    assert config.runtime_mode == "evo"
    assert config.enable_tools is True
    assert config.filesystem is True
    assert config.git is False
    assert config.bash is False
    assert config.process is False
    assert config.pytest is False
    assert config.ruff is False
    assert config.mypy is False
    assert config.browser is False
    assert config.obsidian_tools is False
    assert config.knowledge_augmentation is False
    assert config.memory is False
