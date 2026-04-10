from __future__ import annotations

"""Named runtime profile resolution for interface/runtime adapter assembly.

This module is the single naming-layer entry for default runtime surface shapes.
It prevents the adapter/build entrypoints from growing a parallel public API of
ad-hoc capability booleans while still allowing a compatibility bridge for older
callers that pass explicit flags.
"""

from dataclasses import dataclass, field
from typing import Literal

from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile
from orbit.runtime.governance.protocol.mode import RuntimeMode

RuntimeProfileName = Literal["runtime_core_minimal", "mcp_default"]


@dataclass(frozen=True)
class RuntimeProfileSpec:
    name: RuntimeProfileName
    runtime_mode: RuntimeMode = "dev"
    model: str = "gpt-5.4"
    enable_tools: bool = True
    capability_profile: RuntimeCapabilityProfile = field(default_factory=RuntimeCapabilityProfile)
    knowledge_augmentation: bool = False
    memory: bool = False


def resolve_runtime_profile(
    profile_name: RuntimeProfileName,
    *,
    runtime_mode: RuntimeMode = "dev",
    model: str = "gpt-5.4",
) -> RuntimeProfileSpec:
    if profile_name == "runtime_core_minimal":
        return RuntimeProfileSpec(
            name="runtime_core_minimal",
            runtime_mode=runtime_mode,
            model=model,
            enable_tools=True,
            capability_profile=RuntimeCapabilityProfile(),
            knowledge_augmentation=False,
            memory=False,
        )
    if profile_name == "mcp_default":
        return RuntimeProfileSpec(
            name="mcp_default",
            runtime_mode=runtime_mode,
            model=model,
            enable_tools=True,
            capability_profile=RuntimeCapabilityProfile(filesystem=True),
            knowledge_augmentation=False,
            memory=False,
        )
    raise ValueError(f"unknown runtime profile: {profile_name}")


def runtime_profile_name_for_capabilities(capability_profile: RuntimeCapabilityProfile) -> RuntimeProfileName:
    if capability_profile == RuntimeCapabilityProfile():
        return "runtime_core_minimal"
    if capability_profile == RuntimeCapabilityProfile(filesystem=True):
        return "mcp_default"
    return "runtime_core_minimal"


def spec_from_capability_overrides(
    *,
    runtime_mode: RuntimeMode = "dev",
    model: str = "gpt-5.4",
    enable_tools: bool = True,
    filesystem: bool = False,
    git: bool = False,
    bash: bool = False,
    process: bool = False,
    pytest: bool = False,
    ruff: bool = False,
    mypy: bool = False,
    browser: bool = False,
    obsidian_tools: bool = False,
    knowledge_augmentation: bool = False,
    memory: bool = False,
) -> RuntimeProfileSpec:
    capability_profile = RuntimeCapabilityProfile(
        filesystem=filesystem,
        git=git,
        bash=bash,
        process=process,
        pytest=pytest,
        ruff=ruff,
        mypy=mypy,
        browser=browser,
        obsidian=obsidian_tools,
        memory=memory,
    )
    return RuntimeProfileSpec(
        name=runtime_profile_name_for_capabilities(capability_profile),
        runtime_mode=runtime_mode,
        model=model,
        enable_tools=enable_tools,
        capability_profile=capability_profile,
        knowledge_augmentation=knowledge_augmentation,
        memory=memory,
    )
