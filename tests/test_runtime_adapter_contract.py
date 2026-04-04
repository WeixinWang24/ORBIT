from __future__ import annotations

from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig


def test_runtime_adapter_contract_surface_is_declared() -> None:
    config = RuntimeAdapterConfig()
    assert config.model == "gpt-5.4"
    assert config.enable_tools is False
    assert config.enable_mcp_filesystem is False
    assert config.enable_mcp_bash is False
    assert config.enable_mcp_process is False
