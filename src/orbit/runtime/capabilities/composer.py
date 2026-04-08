from __future__ import annotations

from dataclasses import dataclass, field
import time
from pathlib import Path
from typing import Any

from orbit.runtime.mcp.bootstrap import (
    bootstrap_local_filesystem_mcp_server,
    bootstrap_local_git_mcp_server,
    bootstrap_local_obsidian_mcp_server,
)
from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
from orbit.runtime.mcp.browser_bootstrap import bootstrap_local_browser_mcp_server
from orbit.runtime.mcp.mypy_bootstrap import bootstrap_local_mypy_mcp_server
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
from orbit.runtime.mcp.pytest_bootstrap import bootstrap_local_pytest_mcp_server
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.runtime.mcp.ruff_bootstrap import bootstrap_local_ruff_mcp_server
from orbit.tools.registry import ToolRegistry


@dataclass
class RuntimeCapabilityProfile:
    enable_mcp_filesystem: bool = False
    enable_mcp_git: bool = False
    enable_mcp_bash: bool = False
    enable_mcp_process: bool = False
    enable_mcp_pytest: bool = False
    enable_mcp_ruff: bool = False
    enable_mcp_mypy: bool = False
    enable_mcp_browser: bool = False
    enable_mcp_obsidian: bool = False
    enable_memory: bool = False


@dataclass
class RuntimeCapabilityBundle:
    tool_registry: ToolRegistry
    embedding_service: Any | None = None
    memory_service: Any | None = None
    enabled_families: set[str] = field(default_factory=set)
    activation_metrics: dict[str, float] = field(default_factory=dict)
    warmup_metrics: dict[str, float] = field(default_factory=dict)


class RuntimeCapabilityComposer:
    def __init__(self, *, workspace_root: str, backend=None):
        self.workspace_root = str(workspace_root)
        self.backend = backend

    def _record(self, bucket: dict[str, float], key: str, started_at: float) -> None:
        bucket[key] = round((time.perf_counter() - started_at) * 1000, 2)

    def _activate_mcp_family(self, *, bundle: RuntimeCapabilityBundle, family: str, bootstrap_factory) -> None:
        t = time.perf_counter()
        bootstrap = bootstrap_factory()
        register_mcp_server_tools(registry=bundle.tool_registry, bootstrap=bootstrap)
        self._record(bundle.activation_metrics, f'{family}_activation_ms', t)
        bundle.enabled_families.add(family)

    def _maybe_enable_memory(self, *, bundle: RuntimeCapabilityBundle) -> None:
        if bundle.memory_service is not None:
            return
        t = time.perf_counter()
        from orbit.memory import EmbeddingService, MemoryService
        self._record(bundle.activation_metrics, 'memory_import_deferred_ms', t)
        t = time.perf_counter()
        bundle.embedding_service = EmbeddingService()
        self._record(bundle.activation_metrics, 'embedding_service_init_ms', t)
        t = time.perf_counter()
        bundle.memory_service = MemoryService(store=getattr(self.backend, 'store', None), embedding_service=bundle.embedding_service)
        self._record(bundle.activation_metrics, 'memory_service_init_ms', t)
        if hasattr(self.backend, 'memory_service'):
            t = time.perf_counter()
            self.backend.memory_service = bundle.memory_service
            self._record(bundle.activation_metrics, 'backend_memory_service_bind_ms', t)
        bundle.enabled_families.add('memory')

    def activate(self, profile: RuntimeCapabilityProfile) -> RuntimeCapabilityBundle:
        t0 = time.perf_counter()
        bundle = RuntimeCapabilityBundle(tool_registry=ToolRegistry(Path(self.workspace_root)))
        bundle.activation_metrics['tool_registry_init_ms'] = round((time.perf_counter() - t0) * 1000, 2)

        if profile.enable_mcp_filesystem:
            self._activate_mcp_family(
                bundle=bundle,
                family='filesystem',
                bootstrap_factory=lambda: bootstrap_local_filesystem_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_git:
            self._activate_mcp_family(
                bundle=bundle,
                family='git',
                bootstrap_factory=lambda: bootstrap_local_git_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_bash:
            self._activate_mcp_family(
                bundle=bundle,
                family='bash',
                bootstrap_factory=lambda: bootstrap_local_bash_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_process:
            self._activate_mcp_family(
                bundle=bundle,
                family='process',
                bootstrap_factory=lambda: bootstrap_local_process_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_pytest:
            self._activate_mcp_family(
                bundle=bundle,
                family='pytest',
                bootstrap_factory=lambda: bootstrap_local_pytest_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_ruff:
            self._activate_mcp_family(
                bundle=bundle,
                family='ruff',
                bootstrap_factory=lambda: bootstrap_local_ruff_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_mypy:
            self._activate_mcp_family(
                bundle=bundle,
                family='mypy',
                bootstrap_factory=lambda: bootstrap_local_mypy_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_browser:
            self._activate_mcp_family(
                bundle=bundle,
                family='browser',
                bootstrap_factory=lambda: bootstrap_local_browser_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.enable_mcp_obsidian:
            import os
            vault_root = os.environ.get('ORBIT_OBSIDIAN_VAULT_ROOT', '').strip()
            if vault_root:
                self._activate_mcp_family(
                    bundle=bundle,
                    family='obsidian',
                    bootstrap_factory=lambda: bootstrap_local_obsidian_mcp_server(vault_root=vault_root),
                )
        if profile.enable_memory:
            self._maybe_enable_memory(bundle=bundle)
        else:
            bundle.activation_metrics['memory_enabled'] = False

        if hasattr(self.backend, 'tool_registry'):
            t = time.perf_counter()
            self.backend.tool_registry = bundle.tool_registry
            self._record(bundle.activation_metrics, 'backend_tool_registry_bind_ms', t)
        bundle.activation_metrics['total_ms'] = round(sum(v for v in bundle.activation_metrics.values() if isinstance(v, (int, float))), 2)
        return bundle

    def warmup(self, bundle: RuntimeCapabilityBundle, *, families: list[str] | None = None) -> dict[str, float]:
        t0 = time.perf_counter()
        selected = set(families or bundle.enabled_families)
        metrics: dict[str, float] = {}
        if 'memory' in selected and bundle.embedding_service is not None:
            step = time.perf_counter()
            try:
                bundle.embedding_service.embed_text('orbit_warmup_prefetch')
            except Exception:
                pass
            metrics['warmup_memory_ms'] = round((time.perf_counter() - step) * 1000, 2)
        for family in sorted(selected):
            metrics.setdefault(f'warmup_{family}_ms', 0.0)
        metrics['warmup_total_ms'] = round((time.perf_counter() - t0) * 1000, 2)
        bundle.warmup_metrics.update(metrics)
        return metrics
