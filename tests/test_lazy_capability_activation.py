"""Validation: lazy capability activation MVP.

Tests that:
1. Minimal baseline (filesystem only) builds significantly faster than full activation
2. ensure_capability() incrementally activates families into existing bundle
3. Background activation produces correct final tool inventory
4. Backend-bound registries see new tools without rebuild
"""
from __future__ import annotations

import os
import time

import pytest


@pytest.fixture
def workspace_root(tmp_path):
    return str(tmp_path)


def _make_composer(workspace_root: str):
    from orbit.runtime.capabilities.composer import RuntimeCapabilityComposer, RuntimeCapabilityProfile
    return RuntimeCapabilityComposer(workspace_root=workspace_root)


def test_baseline_faster_than_full(workspace_root):
    """Minimal baseline (filesystem only) should be faster than full activation."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile

    composer = _make_composer(workspace_root)

    # Full activation
    full_profile = RuntimeCapabilityProfile(
        filesystem=True, git=True, bash=True, process=True,
    )
    t0 = time.perf_counter()
    full_bundle = composer.activate(full_profile)
    full_ms = (time.perf_counter() - t0) * 1000

    # Minimal baseline
    composer2 = _make_composer(workspace_root)
    minimal_profile = RuntimeCapabilityProfile(filesystem=True)
    t0 = time.perf_counter()
    minimal_bundle = composer2.activate(minimal_profile)
    baseline_ms = (time.perf_counter() - t0) * 1000

    print(f"\n=== Timing Comparison ===")
    print(f"Full activation:    {full_ms:.1f}ms  (capabilities: {sorted(full_bundle.enabled_capabilities)})")
    print(f"Minimal baseline:   {baseline_ms:.1f}ms  (capabilities: {sorted(minimal_bundle.enabled_capabilities)})")
    print(f"Speedup factor:     {full_ms / max(baseline_ms, 0.01):.1f}x")

    assert 'filesystem' in minimal_bundle.enabled_capabilities
    assert 'git' not in minimal_bundle.enabled_capabilities
    assert baseline_ms < full_ms, f"baseline ({baseline_ms:.1f}ms) should be faster than full ({full_ms:.1f}ms)"


def test_ensure_capability_incremental(workspace_root):
    """ensure_capability adds a family into an existing bundle."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile

    composer = _make_composer(workspace_root)
    bundle = composer.activate(RuntimeCapabilityProfile(filesystem=True))

    initial_tools = len(bundle.tool_registry.list_tools())
    assert 'git' not in bundle.enabled_capabilities

    # Incrementally activate git
    activated = composer.ensure_capability(bundle, 'git')
    assert activated is True
    assert 'git' in bundle.enabled_capabilities
    assert 'git_activation_ms' in bundle.activation_metrics

    # Second call is a no-op
    activated_again = composer.ensure_capability(bundle, 'git')
    assert activated_again is False

    # Tools were added to the same registry
    final_tools = len(bundle.tool_registry.list_tools())
    assert final_tools > initial_tools, f"tool count should grow: {initial_tools} -> {final_tools}"
    print(f"\nIncremental: {initial_tools} -> {final_tools} tools after git activation")


def test_ensure_capability_all_deferred(workspace_root):
    """All deferred families can be incrementally activated."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile

    composer = _make_composer(workspace_root)
    bundle = composer.activate(RuntimeCapabilityProfile(filesystem=True))

    baseline_tools = len(bundle.tool_registry.list_tools())
    deferred = ['git', 'bash', 'process']
    # Skip obsidian unless ORBIT_OBSIDIAN_VAULT_ROOT is set
    if os.environ.get('ORBIT_OBSIDIAN_VAULT_ROOT', '').strip():
        deferred.append('obsidian')

    for cap in deferred:
        t = time.perf_counter()
        activated = composer.ensure_capability(bundle, cap)
        elapsed = (time.perf_counter() - t) * 1000
        assert activated is True, f"{cap} should have been newly activated"
        print(f"  {cap}: activated in {elapsed:.1f}ms")

    final_tools = len(bundle.tool_registry.list_tools())
    print(f"\nFull incremental: {baseline_tools} -> {final_tools} tools")
    print(f"Enabled capabilities: {sorted(bundle.enabled_capabilities)}")
    assert final_tools > baseline_tools


def test_background_activate_via_adapter(workspace_root):
    """SessionManagerRuntimeAdapter.background_activate_capabilities works."""
    from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig, SessionManagerRuntimeAdapter

    t0 = time.perf_counter()
    adapter = SessionManagerRuntimeAdapter.build(
        RuntimeAdapterConfig(
            runtime_mode="dev",
            runtime_profile="mcp_default",
        )
    )
    baseline_ms = (time.perf_counter() - t0) * 1000
    baseline_tools = len(adapter.list_available_tools())

    activated_caps = []
    failed_caps = []

    def on_activated(cap, elapsed):
        activated_caps.append(cap)

    def on_failed(cap, exc):
        failed_caps.append(cap)

    deferred = ['git', 'bash', 'process']
    t0 = time.perf_counter()
    metrics = adapter.background_activate_capabilities(
        deferred,
        on_capability_activated=on_activated,
        on_capability_failed=on_failed,
    )
    bg_ms = (time.perf_counter() - t0) * 1000

    final_tools = len(adapter.list_available_tools())

    print(f"\n=== Adapter Background Activation ===")
    print(f"Baseline build:     {baseline_ms:.1f}ms ({baseline_tools} tools)")
    print(f"Background activation: {bg_ms:.1f}ms")
    print(f"Final tool count:   {final_tools}")
    print(f"Activated:          {activated_caps}")
    print(f"Failed:             {failed_caps}")
    print(f"Metrics:            {metrics}")

    assert set(activated_caps) == set(deferred)
    assert not failed_caps
    assert final_tools > baseline_tools


def test_background_activate_obsidian_skip_does_not_fail(workspace_root, monkeypatch):
    """Optional obsidian background activation should settle as skipped, not failed or stuck."""
    from orbit.interfaces.runtime_adapter import RuntimeAdapterConfig, SessionManagerRuntimeAdapter
    from orbit.runtime import project_env

    monkeypatch.setattr(project_env, 'load_env_local', lambda override=True: False)
    old_val = os.environ.pop('ORBIT_OBSIDIAN_VAULT_ROOT', None)
    try:
        adapter = SessionManagerRuntimeAdapter.build(
            RuntimeAdapterConfig(
                runtime_mode="dev",
                runtime_profile="mcp_default",
            )
        )
        activated_caps = []
        failed_caps = []
        metrics = adapter.background_activate_capabilities(
            ['obsidian'],
            on_capability_activated=lambda cap, elapsed: activated_caps.append(cap),
            on_capability_failed=lambda cap, exc: failed_caps.append(cap),
        )
        assert activated_caps == ['obsidian']
        assert failed_caps == []
        assert metrics.get('bg_obsidian_skipped') is True
    finally:
        if old_val is not None:
            os.environ['ORBIT_OBSIDIAN_VAULT_ROOT'] = old_val


def test_full_activation_still_works(workspace_root):
    """Full activation path is preserved (not broken by lazy changes)."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile

    composer = _make_composer(workspace_root)
    profile = RuntimeCapabilityProfile(
        filesystem=True, git=True, bash=True, process=True,
    )
    bundle = composer.activate(profile)
    assert 'filesystem' in bundle.enabled_capabilities
    assert 'git' in bundle.enabled_capabilities
    assert 'bash' in bundle.enabled_capabilities
    assert 'process' in bundle.enabled_capabilities
    print(f"\nFull activation: {sorted(bundle.enabled_capabilities)}, {len(bundle.tool_registry.list_tools())} tools")


def test_obsidian_env_gating(workspace_root, monkeypatch):
    """Obsidian ensure_capability is skipped when neither env nor project-local config provides a vault root."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile
    from orbit.runtime import project_env

    composer = _make_composer(workspace_root)
    bundle = composer.activate(RuntimeCapabilityProfile(filesystem=True))

    old_val = os.environ.pop('ORBIT_OBSIDIAN_VAULT_ROOT', None)
    monkeypatch.setattr(project_env, 'load_env_local', lambda override=True: False)
    try:
        activated = composer.ensure_capability(bundle, 'obsidian')
        assert activated is False, "obsidian should not activate without env or .env.local vault config"
    finally:
        if old_val is not None:
            os.environ['ORBIT_OBSIDIAN_VAULT_ROOT'] = old_val


def test_obsidian_env_local_fallback(workspace_root, monkeypatch):
    """Obsidian ensure_capability may activate from project-local .env.local-backed config."""
    from orbit.runtime.capabilities.composer import RuntimeCapabilityProfile
    from orbit.runtime import project_env

    composer = _make_composer(workspace_root)
    bundle = composer.activate(RuntimeCapabilityProfile(filesystem=True))

    old_val = os.environ.pop('ORBIT_OBSIDIAN_VAULT_ROOT', None)

    def _fake_load_env_local(*, override=True):
        os.environ['ORBIT_OBSIDIAN_VAULT_ROOT'] = '/Volumes/2TB/MAS/vio_vault'
        return True

    monkeypatch.setattr(project_env, 'load_env_local', _fake_load_env_local)
    try:
        activated = composer.ensure_capability(bundle, 'obsidian')
        assert activated is True, 'obsidian should activate when .env.local fallback provides a vault root'
    finally:
        if old_val is None:
            os.environ.pop('ORBIT_OBSIDIAN_VAULT_ROOT', None)
        else:
            os.environ['ORBIT_OBSIDIAN_VAULT_ROOT'] = old_val
